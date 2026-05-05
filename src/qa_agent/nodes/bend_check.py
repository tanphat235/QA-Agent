from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from qa_agent.state import GraphState, Issue

_SYSTEM = """\
You are a structural drawing QA specialist reviewing bending details in rebar/reinforcement drawings.

Inspect the drawing text for violations of standard bending rules:
- Bend radius less than the minimum allowed for the bar size (typically 2–4× bar diameter)
- Hook length or extension not meeting code minimums (e.g., ACI 318 standard hooks)
- Bending shape codes that are undefined, inconsistent, or contradictory
- Missing bend angles or conflicting geometry dimensions
- Discrepancies between bending schedule values and drawn details

Return only genuine issues. If the details are code-compliant, return an empty issues list.\
"""


class _BendIssue(BaseModel):
    severity: str = Field(description="error, warning, or info")
    description: str = Field(description="Concise description of the bending issue")
    page: int = Field(description="1-indexed page number where the issue appears")
    location: str = Field(description="Location on the page, e.g. 'detail D3 bend schedule row 4'")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")


class _BendResult(BaseModel):
    issues: list[_BendIssue] = Field(default_factory=list)


def bend_check(state: GraphState) -> dict:
    content = state.get("pdf_content")
    if not content:
        return {"bend_issues": []}

    llm = ChatAnthropic(model="claude-sonnet-4-5").with_structured_output(_BendResult)
    result: _BendResult = llm.invoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=f"Drawing text to validate:\n\n{content['raw_text']}"),
    ])

    issues: list[Issue] = [
        {
            "category": "bend",
            "severity": item.severity,
            "description": item.description,
            "page": item.page,
            "location": item.location,
            "confidence": item.confidence,
        }
        for item in result.issues
    ]

    return {"bend_issues": issues}
