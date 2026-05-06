import base64
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from qa_agent.state import GraphState, Issue

_SYSTEM = """\
You are a senior structural rebar detailing QA reviewer.

Your task is to review the entire PDF drawing visually and contextually.
Do NOT extract the drawing content.
Do NOT summarize the drawing.
Only report clear, objective QA issues related to text, section references, title block, overview consistency, and connected-element annotations.

You must inspect the whole drawing, including:
- all visible text
- section titles
- section symbols / section callouts
- title block
- overview / key plan / general view
- member names
- connected component annotations
- notes and labels

CHECKS TO PERFORM:

1. Spelling check
- Identify clear spelling mistakes in visible text.
- Do not flag accepted engineering abbreviations.
- Do not flag capitalization style unless it creates ambiguity.
- Do not flag unclear text unless it is genuinely unreadable.

2. Section name consistency
- Check whether section names/titles match their corresponding section symbols or callouts.
- Example issue: section callout says "SECTION 2" but the detail title says "SECTION 3".
- Only report if the mismatch is clearly visible.

3. Section scale consistency
- Check whether section/detail scales match the scale information in the title block or drawing references.
- Only report if both values are visible and clearly inconsistent.
- Do not guess scale from geometry.

4. Title block abnormality
- Check for missing, inconsistent, or suspicious title block information.
- Examples:
  - missing drawing title
  - missing drawing number
  - missing revision
  - conflicting scale information
  - project/member title inconsistent with drawing content
  - obviously incomplete title block
- Do not report optional fields unless their absence is clearly abnormal for this drawing.

5. Overview / overall section consistency
- Identify the overview, key plan, or overall section view that shows the general position of the structural members/components.
- Check whether the components annotated in the overview match the components actually presented in the drawing details.
- Verify that each referenced component has the correct name, label, and relative position between the overview and the detailed views.
- Report clear mismatches, such as:
  - overview labels component "B1" but the corresponding detail is labeled "B2"
  - overview shows a component on the left side, but the detail/reference indicates it is on the right side
  - overview references a member/component that is not presented in the drawing details
  - a detailed component appears in the drawing but is missing or incorrectly referenced in the overview
- Only report when the overview reference and the detailed component are both clearly visible.
- Do not infer component identity from shape alone.
- Do not guess intended position if the overview or detail reference is ambiguous.
- Do not report missing information unless the omission is obvious and materially affects drawing interpretation.

6. Connected component annotation check
- Check whether connected elements/components are properly annotated.
- Report if a connected component is clearly missing a required label, has a wrong label, or has an ambiguous label.
- Do not invent component identity.
- Do not report if the label is merely outside the cropped visible area or unreadable with low confidence.

STRICT ANTI-HALLUCINATION RULES:
- Report ONLY issues directly visible in the PDF.
- Do NOT infer design intent.
- Do NOT assume office standards that are not shown in the drawing.
- Do NOT report possible issues.
- Do NOT report low-confidence observations.
- If confidence is below 0.85, omit the issue.
- If two pieces of information are not both clearly visible, do not report a mismatch.
- If the drawing is clean, return an empty issues list.

SEVERITY RULES:
- error: clear issue likely to cause construction, fabrication, or interpretation mistakes.
- warning: clear inconsistency or ambiguity that should be reviewed.
- info: minor spelling/text/title-block issue with low practical impact.

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
    description: str = Field(description="Concise description of the issue")
    page: int = Field(description="1-indexed page number where the issue appears")
    location: str = Field(description="Approximate visual location, e.g. 'top-right title block'")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")


class _SpellResult(BaseModel):
    issues: list[_SpellIssue] = Field(default_factory=list)


def spell_check(state: GraphState) -> dict:
    with open(state["pdf_path"], "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",
        temperature=0,
        max_tokens=2048,
    ).with_structured_output(_SpellResult).with_retry(stop_after_attempt=2)

    result: _SpellResult = llm.invoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=[
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
            },
            {"type": "text", "text": "Review the full drawing PDF and report all QA issues per the instructions."},
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
    ]
    return {"spell_issues": issues}
