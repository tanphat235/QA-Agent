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
Inspect reinforcement labels and dimensions in the section views of this structural drawing.
Report ONLY issues you can directly observe from visible annotations in the PDF.

CHECK 1 — Unlabeled Reinforcement (rebar_label)
For each section view (Schnitt), flag any reinforcement element with no explicit label:
  • Bar shown as solid circle/oval with no Ø or Pos number directly adjacent or connected by a leader line
  • Bar group or layer with no shared callout explicitly covering that group
  • Stirrup outline with no Pos reference or hook dimension shown
Do NOT flag if a label is present but simply located nearby with a clear leader line.
Do NOT flag if the drawing uses a consistent "typical" note that visibly covers that view.

CHECK 2 — Missing Rebar Dimensions (rebar_dims)
For each section view, flag where a bar group's positional information is clearly incomplete:
  • No concrete cover dimension and no standard cover note that covers this specific bar
  • No bar spacing dimension where bars are at regular spacing with no value shown
  • No lap/splice length where a lap zone is clearly visible but undimensioned
Do NOT flag if a general note or schedule entry unambiguously applies to the specific bar.

CHECK 3 — Cross-View Inconsistency (cross_view)
Flag where the same bar mark or Pos number appears in two different section views with
clearly different diameters, spacing, or quantities that cannot be explained by the view type.
Only flag where BOTH references are simultaneously visible and unambiguously different.

CHECK 4 — Starter Bar / Lap Splice Issues (starter_bars)
Flag starter bars, dowels, or lap splice zones that are clearly visible but missing:
  • A bar mark or Pos number
  • A lap length or projection dimension
Do NOT flag where the dimension or mark is present but difficult to read.

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       "rebar_label" | "rebar_dims" | "cross_view" | "starter_bars"
  severity:    "error" for missing label/dimension causing fabrication risk; "warning" for ambiguous
  description: concise — name the specific Schnitt and element
  page:        1
  location:    specific location (e.g. "Schnitt 6-6, top-right corner" or "wall base lap zone")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65

RULES:
  • Only report issues directly visible and unambiguous.
  • A faint but legible label is still a label — do not flag it.
  • If no issues are found for all checks, return an empty list — that is correct.\
"""

# Python generates pass/fail summaries — LLM never needs to produce them.
_CHECK_META: dict[str, tuple[str, str]] = {
    "rebar_label": (
        "Rebar Label Completeness",
        "PASS — all reinforcement elements labeled in section views.",
    ),
    "rebar_dims": (
        "Rebar Dimension Completeness",
        "PASS — all required dimensions present in section views.",
    ),
    "cross_view": (
        "Cross-View Consistency",
        "PASS — no cross-view inconsistencies found.",
    ),
    "starter_bars": (
        "Starter Bars & Lap Splices",
        "PASS — all starter bars and lap splices properly marked.",
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


class _RebarIssue(BaseModel):
    check: str = Field(description="rebar_label | rebar_dims | cross_view | starter_bars")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _RebarResult(BaseModel):
    issues: list[_RebarIssue]  # required — no default so missing field raises ValidationError


def rebar_check(state: GraphState) -> dict:
    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_RebarResult).with_retry(stop_after_attempt=2)

    result: _RebarResult = llm.invoke(  # type: ignore[assignment]
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
        config={"callbacks": [_UsageCallback("rebar_check")]},
    )
    print(f"[usage][rebar_check] raw items from LLM: {len(result.issues)}")

    # Group LLM findings by check category, filter low-confidence
    by_check: dict[str, list[_RebarIssue]] = {k: [] for k in _CHECK_META}
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
            "category": "rebar",
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
                "category": "rebar",
                "severity": item.severity,
                "description": item.description,
                "page": item.page,
                "location": item.location,
                "confidence": item.confidence,
            })

    return {"rebar_issues": issues}
