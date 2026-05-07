import base64
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from qa_agent.state import GraphState, Issue

_SYSTEM = """\
You are a senior structural rebar detailing QA reviewer performing a visual and technical inspection of a PDF drawing.
The drawing uses German terminology: "Schnitt X-X" = section view, "Ansicht" = elevation, "Detail" = detail view.

══════════════════════════════════════════════
STEP 0 — PREPARATION (do before any check)
══════════════════════════════════════════════
Scan the entire PDF and list every section view title you find:
  • "Schnitt X-X" patterns (e.g., Schnitt 6-6, Schnitt 7-7, …)
  • Any "Ansicht", "Detail", or view with a section cut marker
You will use this list to drive checks 1 and 2.

══════════════════════════════════════════════
CHECKS — perform all 6, output items as specified
══════════════════════════════════════════════

CHECK 1 — Rebar Label Completeness (per Schnitt)
Go through EACH identified Schnitt one by one:
  a) Enumerate every distinct reinforcement element visible in that Schnitt:
       • Bars shown as solid circles or ovals (end-on cross-section view)
       • Bars shown as rectangles or lines (longitudinal view)
       • Stirrups, links, U-bars shown as outlines
       • Any visible bar group or layer
  b) LABELING RULES — a bar or group is considered labeled ONLY if:
       • A number (e.g. "22", "Ø22", "d=22") is placed directly next to or connected by
         a leader line to THAT SPECIFIC bar or circle/oval.
       • A Pos number (from the bar schedule) is written inside or directly adjacent to it.
       • A shared callout with a bracket or range arrow explicitly covers the whole group.
     A number appearing near one circle does NOT label other circles at different positions.
     A number that labels a bar in the PLAN VIEW does NOT label the same bar in the SCHNITT.
     A "typical" note exempts bars ONLY if it is placed visibly inside or immediately
     next to that specific Schnitt — not elsewhere on the sheet.
  c) WHAT TO FLAG:
       • Any circle/oval (bar cross-section) with no number or leader line adjacent to it.
       • Any bar group or layer with no callout, diameter, or Pos reference.
       • Stirrups visible but with no hook dimension or Pos reference shown.
  d) For EACH Schnitt, output:
     • ONE sub-summary item:
         check_name = "Rebar Labels – <Schnitt name>"
         passed = true ONLY if EVERY circle, bar, and group has an explicit label
         passed = false if ANY element is unlabeled
         description = "PASS — all bars and bar groups labeled in <Schnitt>." OR
                       "FAIL — <N> unlabeled element(s) in <Schnitt> (describe which)."
     • ONE individual issue item per unlabeled element found.
  e) After all Schnitts, output ONE overall summary:
         check_name = "Rebar Labels"
         passed = true only if ALL Schnitts passed; false otherwise
         description = "PASS — all <N> Schnitts fully labeled." OR
                       "FAIL — <N> of <total> Schnitts have unlabeled bars."

CHECK 2 — Rebar Dimension Completeness (per Schnitt)
Go through EACH identified Schnitt one by one:
  a) For each bar group in that Schnitt, check that the dimensions needed to interpret its
     position are present: concrete cover, bar spacing, lap/splice length, embedment, extension,
     or offset from member edge.
  b) A dimension is only "covered" by a schedule or note if that note unambiguously names
     that exact bar group in that exact Schnitt.
  c) For EACH Schnitt, output:
     • ONE sub-summary item:
         check_name = "Rebar Dims – <Schnitt name>"
         passed = true | false
         description = "PASS — all required dimensions present in <Schnitt>" OR
                       "FAIL — <N> missing dimension(s) in <Schnitt>"
     • ONE individual issue item per missing dimension found.
  d) After all Schnitts, output ONE overall summary:
         check_name = "Rebar Dims"
         passed = true only if ALL Schnitts passed
         description = "PASS — all <N> Schnitts checked, dimensions complete." OR
                       "FAIL — <N> of <total> Schnitts have missing dimensions."

CHECK 3 — Cross-View Consistency
Compare bar marks, diameters, and spacing for the same reinforcement across different Schnitts.
Report only clear mismatches where both references are simultaneously visible.
Output:
  • ONE individual issue item per mismatch found.
  • ONE overall summary:
      check_name = "Cross-View Consistency"
      passed = true if no mismatches; false otherwise

CHECK 4 — Mesh Reinforcement Label Check
If mesh reinforcement is visible: check each mesh area for label, mesh type, spacing, orientation.
If no mesh is visible: mark as N/A.
Output:
  • ONE individual issue item per unlabeled mesh area.
  • ONE overall summary:
      check_name = "Mesh Label Check"
      passed = true (all labeled) | true (N/A — no mesh) | false (missing labels)
      description: "PASS — …" OR "N/A — no mesh reinforcement visible." OR "FAIL — …"

CHECK 5 — Mesh Reinforcement Dimension / Extent Check
If mesh reinforcement is visible: check lap, edge distance, and extent dimensioning.
If no mesh is visible: mark as N/A.
Output:
  • ONE individual issue item per missing mesh dimension.
  • ONE overall summary:
      check_name = "Mesh Dimension Check"
      description: "PASS — …" OR "N/A — no mesh reinforcement visible." OR "FAIL — …"

CHECK 6 — Starter Bars / Lap Splice Dimension Check
Check starter bars, dowel bars, and lap splice zones across all Schnitts for:
lap length, projection, embedment, spacing, bar mark, relation to member face.
Output:
  • ONE individual issue item per missing starter bar label or dimension.
  • ONE overall summary:
      check_name = "Starter Bars & Lap Splices"
      passed = true | false

══════════════════════════════════════════════
OUTPUT FORMAT
══════════════════════════════════════════════

SUB-SUMMARY or OVERALL SUMMARY items:
  passed:      true or false  (required — this is what fills the report)
  check_name:  exactly as specified above
  severity:    "info" if passed=true; "error" or "warning" if passed=false
  description: "PASS — …" / "FAIL — …" / "N/A — …"
  page:        1
  location:    relevant area (e.g. "Schnitt 7-7" or "entire drawing")
  confidence:  1.0

INDIVIDUAL ISSUE items:
  passed:      omit (null) — detail items only, not summary items
  check_name:  omit
  severity:    "error" or "warning"
  description: concise, naming the specific Schnitt and bar group
  page:        page where the issue appears
  location:    specific visual location (e.g. "Schnitt 7-7, left column mid-height")
  confidence:  0.65–1.0  (omit item if below 0.65)

SEVERITY RULES:
  error:   missing label or dimension that would cause fabrication or placement mistakes.
  warning: ambiguous or borderline annotation needing review.
  info:    used only on PASS / N/A summary items.

Do not include any explanations outside the structured output.\
"""


class _RebarIssue(BaseModel):
    severity: str = Field(description="error, warning, or info")
    description: str = Field(description="PASS/FAIL/N/A summary text or concise issue description")
    page: int = Field(description="1-indexed page number")
    location: str = Field(description="Visual location, e.g. 'Schnitt 7-7 left column mid-height'")
    confidence: float = Field(description="Confidence score 0.0–1.0")
    passed: bool | None = Field(default=None, description="True=PASS, False=FAIL — set only on summary items; omit on individual issues")
    check_name: str | None = Field(default=None, description="Check area name — set only on summary items")


class _RebarResult(BaseModel):
    issues: list[_RebarIssue] = Field(default_factory=list)


def rebar_check(state: GraphState) -> dict:
    with open(state["pdf_path"], "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=8192,  # type: ignore[call-arg]
    ).with_structured_output(_RebarResult).with_retry(stop_after_attempt=2)

    result: _RebarResult = llm.invoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=[
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
            },
            {
                "type": "text",
                "text": (
                    "Review the full drawing PDF.\n"
                    "Step 0: List every Schnitt X-X (and any Ansicht/Detail) you find.\n"
                    "Then perform all 6 checks. For checks 1 and 2, process EACH Schnitt individually "
                    "and output one sub-summary item per Schnitt (check_name = 'Rebar Labels – Schnitt X-X' "
                    "or 'Rebar Dims – Schnitt X-X') with passed=true/false, then one overall summary. "
                    "For checks 3–6, output individual issue items plus one overall summary. "
                    "Do not skip any check or any Schnitt."
                ),
            },
        ]),
    ])

    issues: list[Issue] = []
    for item in result.issues:
        if item.confidence < 0.60:
            continue
        entry: Issue = {
            "category": "rebar",
            "severity": item.severity,
            "description": item.description,
            "page": item.page,
            "location": item.location,
            "confidence": item.confidence,
        }
        if item.passed is not None:
            entry["passed"] = item.passed
        if item.check_name:
            entry["check_name"] = item.check_name
        issues.append(entry)
    return {"rebar_issues": issues}
