import base64
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from qa_agent.state import GraphState, Issue

_SYSTEM = """\
You are a senior structural rebar detailing QA reviewer performing a visual and textual inspection of a PDF drawing.

READING INSTRUCTIONS:
- You may read and compare all visible text, tables, labels, symbols, callouts, scales, notes, and diagrams in the PDF.
- Do not reproduce large blocks of raw drawing content in your output.
- Issue descriptions may briefly quote specific visible values (e.g., "callout reads 'SECTION 2' but detail title reads 'SECTION 3'").

CHECKS TO PERFORM:

1. Spelling check
- Identify clear spelling mistakes in all visible text (titles, labels, notes, callouts, title block).
- Do not flag accepted engineering abbreviations (e.g., "Reinf.", "Ø", "typ.", "N.T.S.").
- Do not flag capitalization style unless it creates genuine ambiguity.

2. Section name consistency
- Check whether section names / titles match their corresponding section symbols or callouts.
- Report only when both the callout and the title are clearly visible and clearly differ.

3. Section scale consistency
- Check whether section or detail scales match the scale information in the title block or adjacent references.
- Report only when both values are clearly visible and clearly inconsistent.

4. Title block completeness
- Check for missing or suspicious title block information: drawing title, drawing number, revision, scale, project/member name.
- Report missing fields only when their absence is clearly abnormal for this drawing type.
- Report conflicting information (e.g., two different scale values in the same title block).

5. Overview / key plan consistency
- Identify the overview, key plan, or general layout view showing the position of structural members.
- Check whether member names, labels, and positions in the overview match those in the detailed views.
- Report clear mismatches only when both references are simultaneously visible.

6. Connected component annotation check
- Check whether connected elements are properly annotated (label present, label correct, label unambiguous).
- Report only when a connected component is clearly visible and clearly missing or wrong annotation.

REPORTING RULES:
For EACH of the 6 check areas above, you MUST output at least one result:
- If one or more issues are found: report each as an issue (error / warning / info).
- If no issues are found in a check area: output exactly ONE info item with:
  - severity: "info"
  - description: "✓ [Check name]: [brief description of what was inspected] — no issues found."
  - page: 1
  - location: "entire drawing"
  - confidence: 1.0
  Example: "✓ Spelling check: all visible text, notes, callouts, and title block inspected — no spelling errors found."

MISSING INFORMATION RULE:
- If a required piece of information is missing and its absence prevents completing a check, report it as:
  - severity: "warning"
  - description: "[check area]: required information is missing or unreadable — [what is missing]."
  - confidence: 0.90

CONFIDENCE RULE:
- If your confidence in an issue is below 0.70, omit it.
- Do not report guesses or inferences that cannot be clearly substantiated from the visible content.

SEVERITY RULES:
- error: clear issue that would cause construction, fabrication, or interpretation mistakes.
- warning: clear inconsistency, ambiguity, or missing information that should be reviewed.
- info: minor text/title-block issue with low practical impact, or a clean-check summary (✓).

Each issue must include:
- severity
- concise description
- page number
- approximate visual location
- confidence between 0.0 and 1.0

Do not include explanations outside the structured output.\
"""


class _SpellIssue(BaseModel):
    severity: str = Field(description="error, warning, or info")
    description: str = Field(description="Concise description of the issue or clean-check summary")
    page: int = Field(description="1-indexed page number where the issue appears")
    location: str = Field(description="Approximate visual location, e.g. 'top-right title block'")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")


class _SpellResult(BaseModel):
    issues: list[_SpellIssue] = Field(default_factory=list)


def spell_check(state: GraphState) -> dict:
    with open(state["pdf_path"], "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_SpellResult).with_retry(stop_after_attempt=2)

    result: _SpellResult = llm.invoke([
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
            "category": "spell",
            "severity": item.severity,
            "description": item.description,
            "page": item.page,
            "location": item.location,
            "confidence": item.confidence,
        }
        for item in result.issues
        if item.confidence >= 0.60
    ]
    return {"spell_issues": issues}
