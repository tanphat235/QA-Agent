from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from qa_agent.state import GraphState, Issue

_SYSTEM = """\
You are a structural drawing QA specialist reviewing rebar specifications and schedules.

Inspect the drawing text for:
- Rebar size/designation mismatches between plan view, schedule, and sections
- Spacing values that exceed code-maximum or violate design intent
- Quantity discrepancies between bar marks and the schedule total
- Bar mark labels that are undefined, duplicated with different specs, or missing from the schedule
- Rebar cover dimensions that fall below the minimum required
- Inconsistent units (mixing metric and imperial bar designations)

Return only genuine issues. If the schedule is consistent, return an empty issues list.\
"""


class _RebarIssue(BaseModel):
    severity: str = Field(description="error, warning, or info")
    description: str = Field(description="Concise description of the rebar issue")
    page: int = Field(description="1-indexed page number where the issue appears")
    location: str = Field(description="Location on the page, e.g. 'rebar schedule row B2 / plan grid C-3'")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")


class _RebarResult(BaseModel):
    issues: list[_RebarIssue] = Field(default_factory=list)


def rebar_check(state: GraphState) -> dict:
    content = state.get("pdf_content")
    if not content:
        return {"rebar_issues": []}

    llm = ChatAnthropic(model="claude-sonnet-4-5").with_structured_output(_RebarResult)
    result: _RebarResult = llm.invoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=f"Drawing text to validate:\n\n{content['raw_text']}"),
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
    ]

    return {"rebar_issues": issues}
