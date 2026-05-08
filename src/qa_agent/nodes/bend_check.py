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
Review the bar schedule and section views in this structural drawing.
Report ONLY issues you can directly observe from clearly visible values in the PDF.

CHECK 1 — Bending Angle / Hook Compliance (bending_angle)
Inspect stirrup and hook bending shapes where angle and extension are clearly drawn and labeled.
Flag ONLY if:
  • A stirrup hook is clearly shown at ≤ 90° (EC2 §8.3 requires ≥ 135° unless concrete prevents opening)
  • A straight extension past the last bend is clearly shorter than 5Ø (stirrups: max(10Ø, 70 mm))
  • A mandrel diameter is explicitly labeled and clearly below EC2 minimum (4Ø for Ø ≤ 16 mm; 7Ø for Ø > 16 mm)
Do NOT flag if angle or extension value is not explicitly shown in the diagram.

CHECK 2 — Bar Schedule Mass Arithmetic (mass_arithmetic)
For each Pos where ALL four values are clearly visible in the schedule:
  quantity (n), bar length (m), unit mass (kg/m), shown total mass (kg)
Calculate: expected = n × length × unit_mass
Flag if |shown − expected| / expected > 5%.
Do NOT flag if any of the four required values is missing or unclear.

CHECK 3 — Abnormal Mass Values (abnormal_mass)
Flag any Pos whose shown total mass clearly exceeds 3× the average total of all visible Pos rows,
or exceeds 5 000 kg for a single Pos in a standard member schedule.
Do NOT flag without a clear comparison basis from visible data.

CHECK 4 — Bar Mark Coverage (missing_pos)
Flag any Pos number listed in the bar schedule that does not appear anywhere in the section views,
detail drawings, or bar mark callouts visible on the sheet.
Do NOT flag if the Pos number IS visible somewhere in the drawing.

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       "bending_angle" | "mass_arithmetic" | "abnormal_mass" | "missing_pos"
  severity:    "error" for clear non-compliance; "warning" for borderline or ambiguous
  description: concise — quote Pos number, dimension, or computed vs shown value
  page:        1
  location:    specific location (e.g. "bar schedule row Pos 12" or "Schnitt 3-3")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65

RULES:
  • Only report what is directly visible and unambiguous in the drawing.
  • Do NOT infer or estimate values not shown.
  • Do NOT report a check if required values are not visible.
  • If no issues are found for all checks, return an empty list — that is correct.\
"""

# Python generates pass/fail summaries — LLM never needs to produce them.
_CHECK_META: dict[str, tuple[str, str]] = {
    "bending_angle": (
        "Bending Angle (EC2)",
        "PASS — all visible bending shapes comply with EC2 §8.3.",
    ),
    "mass_arithmetic": (
        "Total Mass Arithmetic",
        "PASS — bar schedule mass arithmetic verified correct.",
    ),
    "abnormal_mass": (
        "Abnormal Mass Detection",
        "PASS — no abnormal mass values detected.",
    ),
    "missing_pos": (
        "Pos Schema Coverage",
        "PASS — all bar positions visible in at least one section view.",
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


class _BendIssue(BaseModel):
    check: str = Field(description="bending_angle | mass_arithmetic | abnormal_mass | missing_pos")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _BendResult(BaseModel):
    issues: list[_BendIssue]  # required — no default so missing field raises ValidationError


def bend_check(state: GraphState) -> dict:
    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_BendResult).with_retry(stop_after_attempt=2)

    result: _BendResult = llm.invoke(  # type: ignore[assignment]
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
        config={"callbacks": [_UsageCallback("bend_check")]},
    )
    print(f"[usage][bend_check] raw items from LLM: {len(result.issues)}")

    # Group LLM findings by check category, filter low-confidence
    by_check: dict[str, list[_BendIssue]] = {k: [] for k in _CHECK_META}
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
            "category": "bend",
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
                "category": "bend",
                "severity": item.severity,
                "description": item.description,
                "page": item.page,
                "location": item.location,
                "confidence": item.confidence,
            })

    return {"bend_issues": issues}
