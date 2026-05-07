import base64
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from qa_agent.state import GraphState, Issue

_SYSTEM = """\
You are a senior structural rebar detailing QA reviewer performing a visual and textual inspection of a PDF drawing.
The drawing uses German terminology: "Schnitt X-X" = section view, "Maßstab" or "M 1:XX" = scale.

══════════════════════════════════════════════
STEP 0 — PREPARATION (do before any check)
══════════════════════════════════════════════
Scan the entire PDF and list every section view title you find:
  • "Schnitt X-X" patterns (e.g., Schnitt 6-6, Schnitt 7-7, …)
  • Any "Ansicht", "Detail", or view with a scale label
You will use this list to drive checks 2 and 3.

══════════════════════════════════════════════
CHECKS — perform all 6, output items as specified
══════════════════════════════════════════════

CHECK 1 — Spelling Check (drawing-wide)
Inspect all visible text in the drawing: titles, labels, notes, callouts, title block.
  • Flag clear spelling mistakes in German or English words.
  • Do NOT flag accepted engineering abbreviations (e.g. "Ø", "typ.", "N.T.S.", "Reinf.", "Bew.").
  • Do NOT flag capitalization style unless it creates genuine ambiguity.
Output:
  • ONE individual issue item per spelling mistake found.
  • ONE overall summary:
      check_name = "Spelling Check"
      passed = true if no mistakes; false if any found
      description = "PASS — all visible text inspected, no spelling errors." OR
                    "FAIL — <N> spelling error(s) found."

CHECK 2 — Section Name Consistency (per Schnitt)
For EACH identified Schnitt, verify that the section title matches the section callout symbol that
points to it in the plan or overview view (e.g., callout "6-6" must match title "Schnitt 6-6").
For EACH Schnitt, output:
  • ONE sub-summary item:
      check_name = "Section Name – <Schnitt name>"
      passed = true (title matches callout) | false (mismatch found) | true (callout not visible — cannot assess)
      description = "PASS — <Schnitt>: title matches callout." OR
                    "FAIL — <Schnitt>: callout reads '<X>' but title reads '<Y>'." OR
                    "N/A — <Schnitt>: corresponding callout not visible in drawing."
  • ONE individual issue item for each mismatch found.
After all Schnitts, output ONE overall summary:
    check_name = "Section Name"
    passed = true only if ALL assessable Schnitts passed
    description = "PASS — all <N> Schnitts checked, names consistent." OR
                  "FAIL — <N> Schnitt name mismatch(es) found."

CHECK 3 — Section Scale Consistency (per Schnitt)
For EACH identified Schnitt that shows a scale label (e.g., "M 1:50"), compare it against:
  a) the title block scale, and
  b) any adjacent scale reference on the same sheet.
For EACH Schnitt with a visible scale, output:
  • ONE sub-summary item:
      check_name = "Section Scale – <Schnitt name>"
      passed = true (scale consistent) | false (mismatch) | true (no scale shown — N/A)
      description = "PASS — <Schnitt>: scale M 1:XX consistent." OR
                    "FAIL — <Schnitt>: section shows M 1:XX but title block/reference shows M 1:YY." OR
                    "N/A — <Schnitt>: no scale label shown."
  • ONE individual issue item for each mismatch found.
After all Schnitts, output ONE overall summary:
    check_name = "Section Scale"
    passed = true only if all assessable Schnitts passed
    description = "PASS — all visible Schnitt scales are consistent." OR
                  "FAIL — <N> scale inconsistency/inconsistencies found."

CHECK 4 — Title Block Completeness (drawing-wide)
Check the title block for these required fields:
  drawing title, drawing number, revision, scale, project name, member name, date, engineer/author.
Flag any field that is clearly missing or left blank when it should be filled.
Also flag conflicting information (e.g. two different revision numbers in the same title block).
Output:
  • ONE individual issue item per missing or conflicting field.
  • ONE overall summary:
      check_name = "Title Block Completeness"
      passed = true if all required fields are present and consistent; false otherwise
      description = "PASS — title block complete, all required fields present." OR
                    "FAIL — <N> missing or conflicting title block field(s)."

CHECK 5 — Overview / Key Plan Consistency (drawing-wide)
Identify the overview or key plan view showing the position of structural members.
Compare member names, labels, and section cut positions in the overview against those in the
detailed Schnitt views.
Output:
  • ONE individual issue item per mismatch found.
  • ONE overall summary:
      check_name = "Overview / Key Plan Consistency"
      passed = true if consistent or no overview present (N/A)
      description = "PASS — …" OR "N/A — no overview / key plan visible." OR "FAIL — …"

CHECK 6 — Connected Component Annotation (drawing-wide)
Check whether connected structural elements (adjacent members, supports, interfaces) are
properly annotated: label present, label correct, label unambiguous.
Output:
  • ONE individual issue item per missing or incorrect annotation.
  • ONE overall summary:
      check_name = "Connected Component Annotation"
      passed = true if all connected elements are properly annotated; false otherwise
      description = "PASS — all connected components annotated correctly." OR "FAIL — …"

══════════════════════════════════════════════
OUTPUT FORMAT
══════════════════════════════════════════════

SUB-SUMMARY or OVERALL SUMMARY items:
  passed:      true or false  (required — this is what fills the pass/fail report)
  check_name:  exactly as specified above
  severity:    "info" if passed=true; "error" or "warning" if passed=false
  description: "PASS — …" / "FAIL — …" / "N/A — …"
  page:        1
  location:    relevant area (e.g. "Schnitt 7-7" or "title block" or "entire drawing")
  confidence:  1.0

INDIVIDUAL ISSUE items:
  passed:      omit (null)
  check_name:  omit
  severity:    "error" or "warning"
  description: concise, quoting the specific text, Schnitt name, or field name
  page:        page where the issue appears
  location:    specific visual location
  confidence:  0.65–1.0  (omit item if below 0.65)

SEVERITY RULES:
  error:   clear issue causing construction, fabrication, or interpretation mistakes.
  warning: inconsistency, ambiguity, or missing information that should be reviewed.
  info:    used only on PASS / N/A summary items.

Do not include any explanations outside the structured output.\
"""


class _SpellIssue(BaseModel):
    severity: str = Field(description="error, warning, or info")
    description: str = Field(description="PASS/FAIL/N/A summary text or concise issue description")
    page: int = Field(description="1-indexed page number")
    location: str = Field(description="Visual location, e.g. 'top-right title block' or 'Schnitt 7-7'")
    confidence: float = Field(description="Confidence score 0.0–1.0")
    passed: bool | None = Field(default=None, description="True=PASS, False=FAIL — set only on summary items; omit on individual issues")
    check_name: str | None = Field(default=None, description="Check area name — set only on summary items")


class _SpellResult(BaseModel):
    issues: list[_SpellIssue] = Field(default_factory=list)


def spell_check(state: GraphState) -> dict:
    with open(state["pdf_path"], "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=8192,  # type: ignore[call-arg]
    ).with_structured_output(_SpellResult).with_retry(stop_after_attempt=2)

    result: _SpellResult = llm.invoke([
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
                    "Step 0: List every Schnitt X-X label you find.\n"
                    "Then perform all 6 checks:\n"
                    "  Check 1: individual spelling issues + one overall summary.\n"
                    "  Check 2: for EACH Schnitt output one sub-summary (check_name='Section Name – Schnitt X-X', "
                    "passed=true/false) plus individual issues, then one overall summary.\n"
                    "  Check 3: for EACH Schnitt with a visible scale output one sub-summary "
                    "(check_name='Section Scale – Schnitt X-X', passed=true/false) plus individual issues, "
                    "then one overall summary.\n"
                    "  Checks 4–6: individual issues + one overall summary each.\n"
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
            "category": "spell",
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
    return {"spell_issues": issues}
