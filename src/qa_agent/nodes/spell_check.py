import base64
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from qa_agent.state import GraphState, Issue

_SYSTEM = """\
You are a structural drawing QA specialist reviewing spelling and labeling accuracy.

Inspect the drawing for:
- Misspelled words in annotations, labels, callouts, or notes
- Inconsistent naming conventions (e.g., "Rebar-A" vs "REBAR A" vs "Bar A")
- Missing or illegible labels
- Non-standard or ambiguous abbreviations

Return only genuine issues. If the drawing is clean, return an empty issues list.\
"""


class _SpellIssue(BaseModel):
    severity: str = Field(description="error, warning, or info")
    description: str = Field(description="Concise description of the spelling or labeling issue")
    page: int = Field(description="1-indexed page number where the issue appears")
    location: str = Field(description="Location on the page, e.g. 'top-right annotation block'")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")


class _SpellResult(BaseModel):
    issues: list[_SpellIssue] = Field(default_factory=list)


def spell_check(state: GraphState) -> dict:
    with open(state["pdf_path"], "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    llm = ChatAnthropic(model="claude-sonnet-4-5").with_structured_output(_SpellResult)
    result: _SpellResult = llm.invoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=[
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
            },
            {"type": "text", "text": "Inspect this structural drawing PDF for spelling and labeling issues."},
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
