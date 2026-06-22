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

# All bend checks operate on schedule/table text — no vision required.
# Input: pdfplumber extracted text only. Model: claude-haiku-4-5 (cheap, fast).
_COMMON_SYSTEM = """\
You are a senior structural QA reviewer for precast concrete wall drawings.

CRITICAL — READ FROM EXTRACTED TEXT ONLY:
  Every value you use (numbers, Pos numbers, bar dimensions, mass totals) MUST be read
  directly from the extracted drawing text provided below. Never use memorized data, training
  knowledge, or information from any previous run or previously seen drawing.
  If a piece of text appears fragmented, garbled, or unclear, do NOT reconstruct or infer its
  intended value — report it as unreadable and add the check to not_found instead.
  Never "imply", "infer", or "reconstruct" a value. If you cannot read it directly, it is not_found.

CRITICAL — NEVER SILENTLY PASS:
  If any information required by a check is missing or not readable in the extracted text,
  you MUST add that check key to not_found. Missing prerequisite = not_found, not pass.

German terminology:
  Stabliste = bar schedule | Mattenstahlliste = mesh rebar schedule | Pos = bar position mark
  Gesamt / Gesamtmasse = total / total mass | Matten-Schneideskizze = mesh cut sketch\
"""

_TASK_INTRO = """\
Review the bar schedule (Stabliste), mesh schedule (Mattenstahlliste), and rebar schemas in this structural drawing.
Report ONLY issues you can directly observe from clearly visible values in the PDF.\
"""

_BEND_CHECKS = [
    "pos_coverage", "mesh_pos", "mesh_ratio",
    "mass_arithmetic", "bending_angle", "bar_length",
]
_CHECK_PROMPTS: dict[str, str] = {k: get_check_prompt("bend", k) for k in _BEND_CHECKS}
_CHECK_META: dict[str, tuple[str, str, str]] = {k: get_check_meta("bend", k) for k in _BEND_CHECKS}

_TASK_OUTRO_TPL = """\

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       {check_keys}
  severity:    "error" for clear non-compliance; "warning" for borderline or ambiguous
  description: concise — quote Pos number, computed vs shown value, or ratio result
  page:        1
  location:    specific location (e.g. "Stabliste row Pos 12" or "Bewehrung Schnitt 3-3")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65
  not_found:   list of check keys where required drawing information was not visible, e.g. ["mesh_pos", "mesh_ratio"]

RULES:
  • OUTPUT ONLY actual problems — values that do not comply, missing items, or clear errors.
  • Do NOT infer or estimate values not shown.
  • If required information is absent from the drawing, add the check key to not_found instead of skipping.

""" + OUTPUT_RULES


def _build_bend_task(enabled_sub: list[str] | None) -> str:
    active = list(_CHECK_PROMPTS.keys()) if enabled_sub is None else [k for k in enabled_sub if k in _CHECK_PROMPTS]
    check_keys = " | ".join(f'"{k}"' for k in active)
    blocks = "\n\n".join(_CHECK_PROMPTS[k] for k in active)
    return _TASK_INTRO + "\n\n" + blocks + _TASK_OUTRO_TPL.format(check_keys=check_keys)



_HIGH_CONFIDENCE_CHECKS = {"pos_coverage"}


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


class _BendIssue(BaseModel):
    check: str = Field(description="pos_coverage | mesh_pos | mesh_ratio | mass_arithmetic | bending_angle | bar_length")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _BendResult(BaseModel):
    issues: list[_BendIssue]
    not_found: list[str] = Field(default_factory=list, description="Check keys where required drawing information was not visible")


def bend_check(state: GraphState) -> dict:
    formatted: str = (state.get("pdf_content") or {}).get("formatted") or ""
    enabled_sub = (state.get("enabled_sub_checks") or {}).get("bend")

    # All bend checks read from schedule/table text — no vision needed.
    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-haiku-4-5",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_BendResult).with_retry(stop_after_attempt=2)

    human_content: list[dict] = [
        {
            "type": "text",
            "text": formatted,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": _build_bend_task(enabled_sub)},
    ]

    result: _BendResult = llm.invoke(  # type: ignore[assignment]
        [
            SystemMessage(content=_COMMON_SYSTEM),
            HumanMessage(content=human_content),
        ],
        config={"callbacks": [_UsageCallback("bend_check")]},
    )
    print(f"[usage][bend_check] raw items from LLM: {len(result.issues)}")

    by_check: dict[str, list[_BendIssue]] = {k: [] for k in _CHECK_META}
    for item in result.issues:
        if item.check not in by_check:
            continue
        threshold = 0.80 if item.check in _HIGH_CONFIDENCE_CHECKS else 0.60
        if accept_finding(item.description, item.confidence, threshold):
            by_check[item.check].append(item)
        else:
            print(f"[{item.check}] dropped non-violation item: {item.description[:100]!r}")

    not_found_set = set(result.not_found or [])
    issues = build_check_issues("bend", _CHECK_META, by_check, not_found_set, enabled_sub)
    issues.extend(run_user_ai_checks("bend", state))
    return {"bend_issues": issues}
