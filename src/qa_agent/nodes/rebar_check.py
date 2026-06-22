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

# ── Model routing ──────────────────────────────────────────────────────────────
# spacer_label     → text only (reads label suffix from extracted text) → Haiku
# pin_width_* and spacer_width → need dimension values from cross-section views;
#   pdfplumber routinely drops dimension-line annotations from graphical views,
#   so we send the rendered PDF to Sonnet for reliable reading.
_VISION_CHECKS = frozenset({"pin_width_vertical", "pin_width_horizontal", "spacer_width"})

# ── System prompts ─────────────────────────────────────────────────────────────
_SYSTEM_TEXT = """\
You are a senior structural QA reviewer for precast concrete wall drawings.

CRITICAL — READ FROM EXTRACTED TEXT ONLY:
  Every value you use (labels, suffixes, part codes) MUST be read directly from the
  extracted drawing text provided below. Never use memorized data or training knowledge.
  If text appears fragmented or unclear, add the check to not_found instead of guessing.

CRITICAL — NEVER SILENTLY PASS:
  If any information required by a check is missing or not readable, you MUST add
  that check key to not_found. Missing prerequisite = not_found, not pass.

German terminology:
  Schnitt X-X = section/cross-section | Ansicht = elevation/formwork view
  Bewehrung = reinforcement/rebar | Pos = bar position/mark\
"""

_SYSTEM_VISION = """\
You are a senior structural QA reviewer for precast concrete wall drawings.
Inspect the PDF drawing visually and technically.

CRITICAL — PREFER THE RENDERED PDF:
  Read dimension values (wall thickness, concrete cover, rebar diameters) directly from
  the rendered cross-section views in the PDF. Extracted text is provided as supplementary
  context only — pdfplumber frequently drops or mis-aligns dimension annotations from
  graphical views (Schnitt, Draufsicht). Always trust what you see in the PDF grid.

CRITICAL — NEVER SILENTLY PASS:
  If any dimension or value required by a check is not visible in the drawing,
  add that check key to not_found. Missing prerequisite = not_found, not pass.

German terminology:
  Schnitt X-X = section/cross-section | Ansicht = elevation/formwork view | Wandansicht = wall elevation
  Bewehrung = reinforcement/rebar | Draufsicht = top/plan view | Maßstab / M 1:XX = scale
  Betondeckung = concrete cover | Cv = design cover (Cmin,dur + ΔCdev)\
"""

_TASK_INTRO = """\
Inspect reinforcement elements, spacers, pin bars, and clamps in this precast wall structural drawing.
Report ONLY issues you can directly observe from visible annotations and dimensions.\
"""

# Shared dimension-extraction block — included in vision group tasks only.
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

_REBAR_CHECKS = ["spacer_label", "pin_width_vertical", "pin_width_horizontal", "spacer_width"]
_CHECK_PROMPTS: dict[str, str] = {k: get_check_prompt("rebar", k) for k in _REBAR_CHECKS}
_CHECK_META: dict[str, tuple[str, str, str]] = {k: get_check_meta("rebar", k) for k in _REBAR_CHECKS}

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


def _build_rebar_task(keys: list[str]) -> str:
    check_keys = " | ".join(f'"{k}"' for k in keys)
    parts: list[str] = [_TASK_INTRO]
    if any(k in _VISION_CHECKS for k in keys):
        parts.append(_STEP_A)
    parts.append("\n\n".join(_CHECK_PROMPTS[k] for k in keys))
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


def _invoke_rebar_group(
    keys: list[str],
    formatted: str,
    pdf_data: str | None,
    use_vision: bool,
) -> _RebarResult:
    """Call the LLM for one routing group (text-only or vision)."""
    task = _build_rebar_task(keys)

    if use_vision:
        model = "claude-sonnet-4-6"
        system = _SYSTEM_VISION
        human_content: list[dict] = []
        if pdf_data:
            human_content.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
                "cache_control": {"type": "ephemeral"},
            })
        if formatted:
            human_content.append({"type": "text", "text": formatted})
    else:
        model = "claude-haiku-4-5"
        system = _SYSTEM_TEXT
        human_content = []
        if formatted:
            human_content.append({
                "type": "text",
                "text": formatted,
                "cache_control": {"type": "ephemeral"},
            })

    human_content.append({"type": "text", "text": task})

    label = f"rebar_{'vision' if use_vision else 'text'}"
    print(f"[rebar_check] {'vision' if use_vision else 'text'} group → {model}: {keys}")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model=model,  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_RebarResult).with_retry(stop_after_attempt=2)

    return llm.invoke(  # type: ignore[return-value]
        [SystemMessage(content=system), HumanMessage(content=human_content)],
        config={"callbacks": [_UsageCallback(label)]},
    )


def rebar_check(state: GraphState) -> dict:
    """Run rebar checks with model routing.

    Routing:
      spacer_label                              → claude-haiku-4-5 (text-only)
      pin_width_vertical / horizontal, spacer_width → claude-sonnet-4-6 + PDF (vision)
    """
    formatted: str = (state.get("pdf_content") or {}).get("formatted") or ""
    pdf_data: str | None = state.get("pdf_data")  # type: ignore[assignment]
    enabled_sub = (state.get("enabled_sub_checks") or {}).get("rebar")

    all_active = (
        list(_CHECK_PROMPTS.keys())
        if enabled_sub is None
        else [k for k in enabled_sub if k in _CHECK_PROMPTS]
    )

    text_keys   = [k for k in all_active if k not in _VISION_CHECKS]
    vision_keys = [k for k in all_active if k in _VISION_CHECKS]

    if vision_keys and not pdf_data:
        print(
            f"[rebar_check] WARNING: {vision_keys} require vision but pdf_data is absent "
            f"— falling back to text-only (claude-haiku-4-5)"
        )
        text_keys   = all_active
        vision_keys = []

    by_check: dict[str, list[_RebarIssue]] = {k: [] for k in _CHECK_META}
    not_found_set: set[str] = set()

    for group_keys, use_vision in ((text_keys, False), (vision_keys, True)):
        if not group_keys:
            continue
        result = _invoke_rebar_group(group_keys, formatted, pdf_data, use_vision)
        print(f"[rebar_check] {'vision' if use_vision else 'text'} raw items: {len(result.issues)}")

        for item in result.issues:
            if item.check not in by_check:
                continue
            if accept_finding(item.description, item.confidence):
                by_check[item.check].append(item)
            else:
                print(f"[{item.check}] dropped non-violation item: {item.description[:100]!r}")

        not_found_set |= set(result.not_found or [])

    issues = build_check_issues("rebar", _CHECK_META, by_check, not_found_set, enabled_sub)
    issues.extend(run_user_ai_checks("rebar", state))
    return {"rebar_issues": issues}
