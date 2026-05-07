import base64
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from qa_agent.state import GraphState, Issue

_SYSTEM = """\
You are a senior structural rebar detailing QA reviewer specialized in Eurocode 2 reinforcement detailing.
You are performing a visual and technical inspection of a PDF drawing.
German terminology: "Schnitt X-X" = section, "Pos" = bar position/mark, "Gesamt" = total, "Stahl" = steel.

══════════════════════════════════════════════
STEP 0 — PREPARATION (do before any check)
══════════════════════════════════════════════
  a) Scan the bar schedule / Bending Shapes table. List every Pos number found.
  b) Scan the drawing. List every Schnitt X-X label found.
You will use these two lists to drive the checks below.

══════════════════════════════════════════════
CHECKS — perform all 7, output items as specified
══════════════════════════════════════════════

CHECK 1 — Bending Angle Compliance (Eurocode 2) — per Pos
For EACH Pos in the bar schedule, inspect its bending shape diagram and verify against EC2 §8.3:
  • Stirrup / closed link hooks: minimum 135° (90° only if concrete prevents opening).
  • Standard bend: minimum 90°.
  • Mandrel diameter: ≥ 4Ø for bar Ø ≤ 16 mm; ≥ 7Ø for bar Ø > 16 mm.
  • Straight extension past last bend: ≥ 5Ø; for stirrups ≥ max(10Ø, 70 mm).
For EACH Pos, output:
  • ONE sub-summary item:
      check_name = "Bending Angle (EC2) – Pos <X>"
      passed = true (compliant or cannot assess — no shape drawn) | false (non-compliant angle/extension)
      description = "PASS — Pos <X>: bending shape complies with EC2." OR
                    "FAIL — Pos <X>: <issue, e.g. hook angle 90° instead of min 135°>."
  • ONE individual issue item per non-compliant angle or extension found.
After all Pos, output ONE overall summary:
    check_name = "Bending Angle (EC2)"
    passed = true only if ALL Pos passed
    description = "PASS — all <N> Pos checked, bending shapes comply." OR
                  "FAIL — <N> of <total> Pos have non-compliant bending angles."

CHECK 2 — Total Mass Existence
Check whether the bar schedule contains a total mass / total weight row or cell
(look for "Gesamt", "Total", "∑ kg", or a summed row at the bottom of the schedule).
Output ONE overall summary only:
    check_name = "Total Mass Existence"
    passed = true if a total mass figure is found; false if none
    description = "PASS — total mass row found: <value> kg." OR
                  "FAIL — no total mass row found in the bar schedule."

CHECK 3 — Total Mass Arithmetic — per Pos
For EACH Pos where diameter, quantity, length, and unit mass are all visible, calculate:
  expected total = quantity × length (m) × unit_mass (kg/m)
Compare to the value shown. Flag Pos where shown value deviates > 5%.
Also verify the grand total equals the sum of all Pos totals (if grand total is visible).
For EACH Pos that has all required values visible, output:
  • ONE sub-summary item:
      check_name = "Mass Arithmetic – Pos <X>"
      passed = true (within 5%) | false (deviation > 5%)
      description = "PASS — Pos <X>: <qty>×<len>m×<unit>kg/m = <expected>kg, shown <shown>kg, OK." OR
                    "FAIL — Pos <X>: expected <expected>kg but schedule shows <shown>kg (deviation <X>%)."
  • ONE individual issue item for each Pos that fails.
After all Pos, output ONE overall summary:
    check_name = "Total Mass Arithmetic"
    passed = true only if all visible Pos and grand total are consistent

CHECK 4 — Abnormal Mass Detection
Flag any Pos whose total mass exceeds 3× the average total mass of all Pos in the schedule,
or any total mass value that appears physically unrealistic for the member type (e.g. > 5 000 kg
for a single-member schedule).
Output:
  • ONE individual issue item per flagged Pos.
  • ONE overall summary:
      check_name = "Abnormal Mass Detection"
      passed = true if all values are within normal range; false if any anomaly found

CHECK 5 — Pos Schema Coverage in Schnitt Views — per Pos
For EACH Pos in the bar schedule, verify that its bending shape, schematic, or placement callout
appears in AT LEAST ONE Schnitt view in the drawing.
A Pos is "covered" if its Pos number, bar mark, or an identical bending shape is clearly visible
inside or directly adjacent to a Schnitt view.
For EACH Pos, output:
  • ONE sub-summary item:
      check_name = "Schema Coverage – Pos <X>"
      passed = true (covered in ≥1 Schnitt) | false (not found in any Schnitt)
      description = "PASS — Pos <X> found in <Schnitt name>." OR
                    "FAIL — Pos <X> has no corresponding schema in any Schnitt view."
  • ONE individual issue item for each Pos that is not covered.
After all Pos, output ONE overall summary:
    check_name = "Schema Coverage"
    passed = true only if ALL Pos are covered
    description = "PASS — all <N> Pos have schema coverage in Schnitt views." OR
                  "FAIL — <N> Pos missing from all Schnitt views: Pos <list>."

CHECK 6 — Mesh Reinforcement Schedule Presence
If mesh reinforcement is shown or referenced: check whether a mesh schedule or usage table is present.
Output ONE overall summary only:
    check_name = "Mesh Schedule Presence"
    passed = true (schedule found) | true (N/A — no mesh) | false (mesh present, no schedule)
    description = "PASS — mesh schedule found." OR "N/A — no mesh reinforcement present." OR
                  "FAIL — mesh reinforcement visible but no schedule found."

CHECK 7 — Mesh Utilisation Ratio
If a mesh schedule is visible: check whether the utilisation ratio is shown and ≥ 85%.
If no mesh schedule: mark N/A.
Output ONE overall summary only:
    check_name = "Mesh Utilisation Ratio"
    passed = true (ratio ≥ 85% or N/A) | false (ratio < 85% or missing)
    description = "PASS — utilisation <X>% ≥ 85%." OR "N/A — no mesh schedule." OR
                  "FAIL — utilisation <X>% below 85%." OR "FAIL — utilisation ratio not shown."

══════════════════════════════════════════════
OUTPUT FORMAT
══════════════════════════════════════════════

SUB-SUMMARY or OVERALL SUMMARY items:
  passed:      true or false  (required — this is what fills the pass/fail report)
  check_name:  exactly as specified above
  severity:    "info" if passed=true; "error" or "warning" if passed=false
  description: "PASS — …" / "FAIL — …" / "N/A — …"
  page:        1
  location:    relevant area (e.g. "bar schedule" or "Schnitt 7-7")
  confidence:  1.0

INDIVIDUAL ISSUE items:
  passed:      omit (null)
  check_name:  omit
  severity:    "error" or "warning"
  description: concise, quoting the Pos number, Schnitt, or specific value
  page:        page where the issue appears
  location:    specific visual location
  confidence:  0.65–1.0  (omit item if below 0.65)

SEVERITY RULES:
  error:   non-compliant angle, arithmetic mismatch, missing total, Pos without schema.
  warning: borderline value, ambiguity, or information needing review.
  info:    used only on PASS / N/A summary items.

Do not include any explanations outside the structured output.\
"""


class _BendIssue(BaseModel):
    severity: str = Field(description="error, warning, or info")
    description: str = Field(description="PASS/FAIL/N/A summary text or concise issue description")
    page: int = Field(description="1-indexed page number")
    location: str = Field(description="Visual location, e.g. 'bar schedule row 4' or 'Schnitt 7-7'")
    confidence: float = Field(description="Confidence score 0.0–1.0")
    passed: bool | None = Field(default=None, description="True=PASS, False=FAIL — set only on summary items; omit on individual issues")
    check_name: str | None = Field(default=None, description="Check area name — set only on summary items")


class _BendResult(BaseModel):
    issues: list[_BendIssue] = Field(default_factory=list)


def bend_check(state: GraphState) -> dict:
    with open(state["pdf_path"], "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=8192,  # type: ignore[call-arg]
    ).with_structured_output(_BendResult).with_retry(stop_after_attempt=2)

    result: _BendResult = llm.invoke([
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
                    "Step 0: List every Pos number from the bar schedule and every Schnitt label.\n"
                    "Then perform all 7 checks:\n"
                    "  Check 1: for EACH Pos output one sub-summary (check_name='Bending Angle – Pos X', passed=true/false) plus individual issues, then one overall summary.\n"
                    "  Check 2: one overall summary only.\n"
                    "  Check 3: for EACH Pos with visible values output one sub-summary (check_name='Mass Arithmetic – Pos X') plus individual issues, then one overall summary.\n"
                    "  Check 4: individual issues + one overall summary.\n"
                    "  Check 5: for EACH Pos output one sub-summary (check_name='Schema Coverage – Pos X', passed=true/false), then one overall summary.\n"
                    "  Checks 6–7: one overall summary each.\n"
                    "Do not skip any check or any Pos."
                ),
            },
        ]),
    ])

    issues: list[Issue] = []
    for item in result.issues:
        if item.confidence < 0.60:
            continue
        entry: Issue = {
            "category": "bend",
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
    return {"bend_issues": issues}
