import base64
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from qa_agent.state import GraphState, Issue

_SYSTEM = """\
You are a senior structural rebar detailing QA reviewer performing a visual and technical inspection of a PDF drawing.

READING INSTRUCTIONS:
- You may read and compare all visible text, tables, labels, dimensions, bar marks, callouts, notes, and section views in the PDF.
- Do not reproduce large blocks of raw drawing content in your output.
- Issue descriptions may briefly quote specific visible values (e.g., "section A-A labels bar as T16-200, but section B-B labels same bar as T12-200").

CHECKS TO PERFORM:

1. Rebar label completeness in sections
- Inspect all section views, details, cuts, and elevations.
- Check whether every visible reinforcement bar group has a label, bar mark, diameter/spacing note, or callout that clearly identifies it.
- Report a bar group only when it is clearly visible and clearly has no identifying label or reference within the drawing.
- Do not report bars covered by a visible typical note, shared callout, legend, or schedule reference.

2. Rebar dimension completeness in sections
- Check whether visible reinforcement bars or bar groups have the required dimensions for understanding their position (cover, spacing, offset, lap, extension, embedment, or relation to concrete edges).
- Report only when the missing dimension is clearly necessary to interpret the bar placement and is not derivable from a visible schedule, note, or callout.

3. Cross-view consistency
- Compare labels, bar marks, dimensions, diameter, and spacing for the same reinforcement across different section views or viewing directions.
- Report only clear mismatches where both references are simultaneously visible in the PDF.

4. Mesh reinforcement label check
- If mesh reinforcement is visible, check whether each mesh area has a clear label, mesh type, spacing, orientation, or reference note.
- Report missing mesh labeling only when mesh is clearly shown and the required identifying information is absent.
- Skip this check (report ✓ not applicable) if no mesh reinforcement is visible.

5. Mesh reinforcement dimension / extent check
- If mesh reinforcement is visible, check whether its extent, lap, edge distance, and orientation are clearly dimensioned or referenced.
- Report only clear missing or inconsistent information that affects installation interpretation.
- Skip this check (report ✓ not applicable) if no mesh reinforcement is visible.

6. Starter bars / lap splice dimension check
- Check whether starter bars, projecting bars, dowel bars, and lap splice zones are clearly dimensioned (lap length, projection, embedment, extension, splice location, spacing, diameter, bar mark, relation to member face).
- Report when a starter bar or splice zone is clearly shown but its required dimension or label is missing.
- Report when lap length or starter bar projection is inconsistent between section views, details, notes, or schedule references where both are visible.
- Do not report if covered by a visible typical note, schedule reference, or shared callout.

REPORTING RULES:
For EACH of the 6 check areas above, you MUST output at least one result:
- If one or more issues are found: report each as an issue (error / warning / info).
- If no issues are found in a check area: output exactly ONE info item with:
  - severity: "info"
  - description: "✓ [Check name]: [brief description of what was inspected] — no issues found."
  - page: 1
  - location: "entire drawing"
  - confidence: 1.0
  Example: "✓ Cross-view consistency: all bar marks and dimensions verified across visible section views — consistent."
- For checks not applicable (no mesh present, no starter bars visible): output one info item:
  - description: "✓ [Check name]: not applicable — [reason]."
  - confidence: 1.0

MISSING INFORMATION RULE:
- If a required piece of information is missing and prevents completing a check, report:
  - severity: "warning"
  - description: "[check area]: required information is missing or unreadable — [what is missing and why it matters]."
  - confidence: 0.90

CONFIDENCE RULE:
- If your confidence in an issue is below 0.70, omit it.
- Do not report bars as unlabeled if a shared typical note, legend, or callout is visible nearby.

SEVERITY RULES:
- error: clear missing or wrong label/dimension likely to cause fabrication, placement, or construction mistakes.
- warning: clear annotation inconsistency, ambiguity, or missing information that should be reviewed.
- info: minor clarity issue with low practical impact, or a clean-check summary (✓).

Each issue must include:
- severity
- concise description
- page number
- approximate visual location
- confidence between 0.0 and 1.0

Do not include explanations outside the structured output.\
"""


class _RebarIssue(BaseModel):
    severity: str = Field(description="error, warning, or info")
    description: str = Field(description="Concise description of the issue or clean-check summary")
    page: int = Field(description="1-indexed page number where the issue appears")
    location: str = Field(description="Approximate visual location, e.g. 'section A-A bottom rebar group'")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")


class _RebarResult(BaseModel):
    issues: list[_RebarIssue] = Field(default_factory=list)


def rebar_check(state: GraphState) -> dict:
    with open(state["pdf_path"], "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_RebarResult).with_retry(stop_after_attempt=2)

    result: _RebarResult = llm.invoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=[
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
            },
            {"type": "text", "text": "Review the full drawing PDF. For each of the 6 check areas, report issues found or a clean summary as instructed."},
        ]),
    ])

    issues: list[Issue] = [
        {
            "category": "rebar",
            "severity": item.severity,
            "description": item.description,
            "page": item.page,
            "location": item.location,
            "confidence": item.confidence,
        }
        for item in result.issues
        if item.confidence >= 0.60
    ]
    return {"rebar_issues": issues}
