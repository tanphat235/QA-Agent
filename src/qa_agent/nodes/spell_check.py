from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from qa_agent.state import GraphState, Issue

_SYSTEM = """\
You are a structural drawing QA specialist reviewing spelling and labeling accuracy.

Inspect the drawing text for:
- Misspelled words in annotations, labels, callouts, or notes
- Inconsistent naming conventions (e.g., "Rebar-A" vs "REBAR A" vs "Bar A")
- Missing or illegible labels
- Non-standard or ambiguous abbreviations

Return only genuine issues. If the text is clean, return an empty issues list.\
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
    content = state.get("pdf_content")
    if not content:
        return {"spell_issues": []}

    llm = ChatAnthropic(model="claude-sonnet-4-5").with_structured_output(_SpellResult)
    result: _SpellResult = llm.invoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=f"Drawing text to validate:\n\n{content['raw_text']}"),
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
