import logging
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.outputs import LLMResult

from qa_agent.state import GraphState
from qa_agent.rag.retriever import get_check_prompt, get_check_meta
from qa_agent.nodes.issue_filter import OUTPUT_RULES, accept_finding, build_check_issues
from qa_agent.nodes.user_ai_checks import run_user_ai_checks

logger = logging.getLogger(__name__)

# Must be byte-for-byte identical across all nodes so Anthropic can share the cached PDF prefix.
_COMMON_SYSTEM = """\
You are a senior structural QA reviewer for precast concrete wall drawings. Inspect the PDF drawing visually and technically.

CRITICAL — READ FROM EXTRACTED TEXT ONLY:
  Every value you use (numbers, labels, part codes, Pos numbers, dimensions, names) MUST be read
  directly from the extracted drawing text provided below. Never use memorized data, training
  knowledge, or information from any previous run or previously seen drawing.
  If a piece of text in the extraction appears fragmented, garbled, or unclear, do NOT reconstruct
  or infer its intended value — report it as unreadable and add the check to not_found instead.
  Never "imply", "infer", or "reconstruct" a value. If you cannot read it directly, it is not_found.

CRITICAL — NEVER SILENTLY PASS:
  If any information required by a check is missing, not visible, or not readable in the drawing,
  you MUST add that check key to not_found. Do NOT assume a check passes just because you cannot
  find the relevant elements. Missing prerequisite = not_found, not pass.

German terminology:
  Schnitt X-X = section/cross-section | Ansicht = elevation/formwork view | Wandansicht = wall elevation
  Bewehrung = reinforcement/rebar | Stabliste = bar list/rebar schedule | Mattenstahlliste = mesh rebar list
  Einbauteilliste = embedded parts list | Montageteilliste = assembly parts list (per element)
  Pos = bar position/mark | Gesamt = total | Stahl = steel | Maßstab / M 1:XX = scale
  Draufsicht = top/plan view | Matten-Schneideskizze = mesh cut sketch | Detail = detail view\
"""

_TASK_INTRO = """\
Inspect reinforcement elements, spacers, pin bars, and clamps in this precast wall structural drawing.
Report ONLY issues you can directly observe from visible annotations and dimensions in the PDF.\
"""

# Shared dimension-extraction block — included whenever any dimension check is active.
_STEP_A = """\
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP A — EXTRACT ACTUAL VALUES FROM THIS DRAWING FIRST
(Complete this step before doing any calculation. Never substitute example numbers.)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A1. wall_width — total wall thickness in cm:
  Read from the FORMWORK cross-section views (Draufsicht X-X, Schnitt X-X in the Ansicht /
  formwork area, NOT the Bewehrung area). A dimension line spanning the full thickness gives
  the value. It may also appear in the title block.
  → Record as: wall_width = [value you read from this drawing] cm

A2. Cv — design concrete cover in cm:
  Read from the title block "BETONDECKUNG" table, column labeled "Cv" (or "Cᵥ"), in mm.
  Divide by 10 to convert to cm. Do NOT use Cmin,dur or ΔCdev.
  → Record as: Cv = [value from BETONDECKUNG table] cm

A3. Ø_layer1 — outermost rebar layer diameter (needed for Horizontal Pin Width check):
  In the SIDE section view (Schnitt a-a in the Bewehrung), find the first rebar layer from
  the wall face inward. Read its label (e.g. "ø 12/15" → Ø12 → 1.2 cm).
  → Record as: Ø_layer1 = [value from this drawing] cm

If any of these values cannot be found in the drawing, do NOT guess or use any number from
the examples below — instead add the affected check key to not_found.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\
"""

# Drop LLM items that describe a passing result instead of an actual violation.
_REBAR_CHECKS = ["spacer_label", "pin_width_vertical", "pin_width_horizontal", "spacer_width"]
_CHECK_PROMPTS: dict[str, str] = {k: get_check_prompt("rebar", k) for k in _REBAR_CHECKS}
_CHECK_META: dict[str, tuple[str, str, str]] = {k: get_check_meta("rebar", k) for k in _REBAR_CHECKS}

# These three checks all require STEP A dimension extraction.
_DIMENSION_CHECKS = {"pin_width_vertical", "pin_width_horizontal", "spacer_width"}

_TASK_OUTRO_TPL = """\

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       {check_keys}
  severity:    "error" for missing/wrong label or incorrect dimension causing fabrication risk; "warning" for ambiguous
  description: concise — quote label text, or state: formula, calculated value, and declared value
  page:        1
  location:    specific location (e.g. "Schnitt 6-6, bottom spacer" or "wall side section, horizontal pin Pos 14")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65
  not_found:   list of check keys where required drawing information was not visible, e.g. ["pin_width_vertical"]

RULES:
  • OUTPUT ONLY actual problems — labels missing suffix, or dimension values that do not match.
  • When flagging a dimension issue, state the formula and both values in the description.
  • If required dimensions or values are not visible in the drawing, add the check key to not_found instead of skipping.

""" + OUTPUT_RULES


def _build_rebar_task(enabled_sub: list[str] | None) -> str:
    active = list(_CHECK_PROMPTS.keys()) if enabled_sub is None else [k for k in enabled_sub if k in _CHECK_PROMPTS]
    check_keys = " | ".join(f'"{k}"' for k in active)
    parts: list[str] = [_TASK_INTRO]
    if any(k in _DIMENSION_CHECKS for k in active):
        parts.append(_STEP_A)
    parts.append("\n\n".join(_CHECK_PROMPTS[k] for k in active))
    parts.append(_TASK_OUTRO_TPL.format(check_keys=check_keys))
    return "\n\n".join(parts)



class _UsageCallback(BaseCallbackHandler):
    def __init__(self, label: str) -> None:
        self.label = label

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        try:
            msg = response.generations[0][0].message  # type: ignore[attr-defined]
            u = getattr(msg, "response_metadata", {}).get("usage", {})
            if not u:
                u = getattr(msg, "usage_metadata", {}) or {}
            print(
                f"[usage][{self.label}] input={u.get('input_tokens', 0)}"
                f"  cache_create={u.get('cache_creation_input_tokens', 0)}"
                f"  cache_read={u.get('cache_read_input_tokens', 0)}"
                f"  output={u.get('output_tokens', 0)}"
            )
        except Exception as exc:
            print(f"[usage][{self.label}] could not read usage: {exc}")


class _RebarIssue(BaseModel):
    check: str = Field(description="spacer_label | pin_width_vertical | pin_width_horizontal | spacer_width")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _RebarResult(BaseModel):
    issues: list[_RebarIssue]
    not_found: list[str] = Field(default_factory=list, description="Check keys where required drawing dimensions were not visible")


def _filter_items(result: _RebarResult) -> dict[str, list[_RebarIssue]]:
    by_check: dict[str, list[_RebarIssue]] = {k: [] for k in _CHECK_META}
    for item in result.issues:
        if item.check in by_check and accept_finding(item.description, item.confidence):
            by_check[item.check].append(item)
        elif item.check in by_check:
            print(f"[{item.check}] dropped non-violation item: {item.description[:100]!r}")
    return by_check


def rebar_check(state: GraphState) -> dict:
    formatted: str = (state.get("pdf_content") or {}).get("formatted") or ""
    enabled_sub = (state.get("enabled_sub_checks") or {}).get("rebar")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-6",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_RebarResult).with_retry(stop_after_attempt=2)

    human_content: list[dict] = [
        {"type": "text", "text": formatted, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": _build_rebar_task(enabled_sub)},
    ]

    result: _RebarResult = llm.invoke(  # type: ignore[assignment]
        [SystemMessage(content=_COMMON_SYSTEM), HumanMessage(content=human_content)],
        config={"callbacks": [_UsageCallback("rebar_check")]},
    )
    print(f"[usage][rebar_check] raw items from LLM: {len(result.issues)}")

    by_check = _filter_items(result)
    not_found_set = set(result.not_found or [])
    issues = build_check_issues("rebar", _CHECK_META, by_check, not_found_set, enabled_sub)
    issues.extend(run_user_ai_checks("rebar", state))
    return {"rebar_issues": issues}
