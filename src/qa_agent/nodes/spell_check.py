import logging
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.outputs import LLMResult

from qa_agent.state import GraphState, Issue

logger = logging.getLogger(__name__)

# Must be byte-for-byte identical across all nodes so Anthropic can share the cached PDF prefix.
_COMMON_SYSTEM = """\
You are a senior structural rebar detailing QA reviewer performing a visual and technical inspection of a PDF structural drawing.
German terminology: "Schnitt X-X" = section view, "Pos" = bar position/mark, "Gesamt" = total, "Stahl" = steel, \
"Maßstab" / "M 1:XX" = scale, "Ansicht" = elevation, "Detail" = detail view.\
"""

_TASK = """\
Inspect visible text and annotations in this structural drawing.
Report ONLY issues you can directly observe in the PDF.

CHECK 1 — Spelling Errors (spelling)
Flag clear spelling mistakes in German or English words in titles, labels, notes, callouts, or title block.
Do NOT flag: accepted engineering abbreviations (Ø, typ., N.T.S., Reinf., Bew.), capitalization style.

CHECK 2 — Section Name vs Callout Mismatch (section_name)
For each "Schnitt X-X" title visible in the drawing, verify it matches the corresponding callout symbol.
Flag only where BOTH the title and its callout are visible AND they clearly differ.
Do NOT flag if only one side is visible.

CHECK 3 — Section Scale Inconsistency (section_scale)
Flag where a Schnitt shows a scale label (M 1:XX) that clearly differs from the title block scale
or a directly adjacent reference scale.
Only flag where both scales are simultaneously visible and unambiguously different.

CHECK 4 — Title Block Missing Fields (title_block)
Check the title block for these required fields:
  drawing title, drawing number, revision, scale, project name, date, engineer/author.
Flag any field that is clearly absent or left blank when it should be filled.

CHECK 5 — Overview / Key Plan Label Mismatch (overview_consistency)
If an overview or key plan view is present: flag member labels or section cut designations that
clearly differ from labels used in the corresponding Schnitt views.
Do NOT flag if no overview/key plan is visible on the sheet.

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       "spelling" | "section_name" | "section_scale" | "title_block" | "overview_consistency"
  severity:    "error" for clear mistake; "warning" for ambiguous or minor
  description: concise — quote the specific text, field, or label involved
  page:        1
  location:    specific location (e.g. "Schnitt 7-7 title" or "title block revision field")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65

RULES:
  • Only report issues directly visible and unambiguous.
  • Do NOT flag uncertain or marginally readable text.
  • If no issues are found for all checks, return an empty list — that is correct.\
"""

# Python generates pass/fail summaries — LLM never needs to produce them.
_CHECK_META: dict[str, tuple[str, str]] = {
    "spelling": (
        "Spelling Check",
        "PASS — no spelling errors found in drawing text.",
    ),
    "section_name": (
        "Section Name Consistency",
        "PASS — all section titles match their callout symbols.",
    ),
    "section_scale": (
        "Section Scale Consistency",
        "PASS — all section scales consistent with title block.",
    ),
    "title_block": (
        "Title Block Completeness",
        "PASS — all required title block fields present.",
    ),
    "overview_consistency": (
        "Overview / Key Plan Consistency",
        "PASS — overview labels consistent with section views.",
    ),
}


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


class _SpellIssue(BaseModel):
    check: str = Field(description="spelling | section_name | section_scale | title_block | overview_consistency")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _SpellResult(BaseModel):
    issues: list[_SpellIssue]  # required — no default so missing field raises ValidationError


def spell_check(state: GraphState) -> dict:
    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_SpellResult).with_retry(stop_after_attempt=2)

    result: _SpellResult = llm.invoke(  # type: ignore[assignment]
        [
            SystemMessage(content=_COMMON_SYSTEM),
            HumanMessage(content=[
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": _TASK,
                },
            ]),
        ],
        config={"callbacks": [_UsageCallback("spell_check")]},
    )
    print(f"[usage][spell_check] raw items from LLM: {len(result.issues)}")

    # Group LLM findings by check category, filter low-confidence
    by_check: dict[str, list[_SpellIssue]] = {k: [] for k in _CHECK_META}
    for item in result.issues:
        if item.confidence >= 0.60 and item.check in by_check:
            by_check[item.check].append(item)

    issues: list[Issue] = []

    # Python always generates a guaranteed pass/fail summary for every check
    for check_key, (check_name, pass_desc) in _CHECK_META.items():
        found = by_check[check_key]
        passed = len(found) == 0
        if passed:
            summary_desc = pass_desc
        elif len(found) == 1:
            summary_desc = f"FAIL — {found[0].description}"
        else:
            summary_desc = f"FAIL — {len(found)} issue(s) found."
        issues.append({
            "category": "spell",
            "check_name": check_name,
            "passed": passed,
            "severity": "info" if passed else "error",
            "description": summary_desc,
            "page": 1,
            "location": "drawing",
            "confidence": 1.0,
        })
        for item in found:
            issues.append({
                "category": "spell",
                "severity": item.severity,
                "description": item.description,
                "page": item.page,
                "location": item.location,
                "confidence": item.confidence,
            })

    return {"spell_issues": issues}
