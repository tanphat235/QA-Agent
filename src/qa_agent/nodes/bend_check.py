import base64
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from qa_agent.state import GraphState, Issue

_SYSTEM = """\
You are a senior structural rebar detailing QA reviewer specialized in Eurocode 2 reinforcement detailing.

Your task is to inspect the entire PDF drawing visually and contextually.
Do NOT extract the drawing content.
Do NOT summarize the drawing.
Only report clear, objective issues related to bar schedule, bending shapes, stirrup hooks, total mass, unusual quantities, and missing bar mark schematics.

CHECKS TO PERFORM:

1. Bar schedule / bending shape check
- Inspect the bar schedule and bending shape diagrams.
- Check whether stirrup bending angles shown in the schedule or bending shape are clearly consistent with Eurocode-style closed link / stirrup detailing.
- Report only if the angle shown is clearly wrong, contradictory, or impossible for the stated shape.
- Do NOT infer angles that are not visible.

2. Stirrup hook / anchorage check
- Check whether stirrup hook length, hook extension, return leg, or anchorage detail is visibly sufficient according to Eurocode 2 / drawing-stated Eurocode requirements.
- Only report if the hook length or anchorage detail is explicitly shown and clearly insufficient, missing, or inconsistent.
- Do NOT calculate Eurocode compliance if required inputs are missing.
- Do NOT assume National Annex values unless they are visible in the drawing or project notes.

3. Total mass check
- Check whether total mass values in the bar schedule are arithmetically consistent with visible values such as diameter, length, quantity, unit mass, and total length.
- Report clear calculation mismatches only when the required input values are visible.
- Do NOT guess missing unit weight, steel density, or hidden schedule fields.

4. Abnormal quantity check by position / mark
- Check whether the quantity of bars for each position / mark appears unusually high or inconsistent compared with the drawing context, repetition count, schedule, and callouts.
- Report only clear anomalies, such as one position having a quantity that contradicts the visible layout or repeated member count.
- Do NOT report merely because a quantity is large.
- Do NOT infer intended quantities from incomplete details.

5. Bar mark schematic coverage
- Identify all visible bar marks / positions listed in the bar schedule.
- Check whether each listed mark has at least one corresponding schematic, bending shape, or placement indication in the drawing.
- Report a missing schematic only when the mark is clearly listed and no corresponding shape/detail/placement reference is visible anywhere in the PDF.
- Do NOT report missing coverage if the mark may be represented by a clearly shared typical detail or grouped shape reference.

6. Mesh reinforcement schedule presence
- If the drawing contains any mesh reinforcement (thép lưới / welded wire mesh / fabric reinforcement), check whether a mesh schedule or mesh usage table is present in the drawing.
- Report as an error if mesh reinforcement is clearly shown or referenced in the drawing but no corresponding mesh schedule or mesh table is visible.
- Do NOT report if no mesh reinforcement is present in the drawing.
- Do NOT report if the mesh schedule may be on a separate referenced sheet that is explicitly cited.

7. Mesh utilisation ratio check
- If a mesh schedule or mesh usage table is visible, check whether the utilisation ratio (used area / total sheet area, or equivalent ratio shown in the table) is above 85% for each mesh sheet or the overall summary.
- Report as a warning if any mesh sheet or the overall utilisation ratio is clearly shown and falls below 85%, indicating poor optimisation and excessive waste.
- Report as an error if the ratio is below 70%.
- Only report when the utilisation ratio or the required input values (used quantity, total quantity, or equivalent) are explicitly visible in the table.
- Do NOT calculate or estimate the ratio if the values are not clearly shown.
- Do NOT assume a default sheet size or standard mesh dimension that is not stated in the drawing.

STRICT ANTI-HALLUCINATION RULES:
- Report ONLY issues directly visible in the PDF.
- Do NOT invent dimensions, bar marks, quantities, angles, or hook lengths.
- Do NOT infer design intent.
- Do NOT assume hidden project standards.
- Do NOT use Eurocode checks when required inputs are not visible.
- Do NOT report possible issues.
- Do NOT report low-confidence observations.
- If confidence is below 0.85, omit the issue.
- If two compared pieces of information are not both clearly visible, do not report a mismatch.
- If the schedule and bending details are clear and consistent, return an empty issues list.

SEVERITY RULES:
- error: clear issue likely to cause fabrication, installation, quantity, or compliance error.
- warning: clear inconsistency or missing information that should be reviewed.
- info: minor clarity issue with low practical impact.

Each issue must include:
- severity
- concise description
- page number
- approximate visual location
- confidence between 0.0 and 1.0

Do not include explanations outside the structured output.\
"""


class _BendIssue(BaseModel):
    severity: str = Field(description="error, warning, or info")
    description: str = Field(description="Concise description of the issue")
    page: int = Field(description="1-indexed page number where the issue appears")
    location: str = Field(description="Approximate visual location, e.g. 'bar schedule row 4'")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")


class _BendResult(BaseModel):
    issues: list[_BendIssue] = Field(default_factory=list)


def bend_check(state: GraphState) -> dict:
    with open(state["pdf_path"], "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=2048,  # type: ignore[call-arg]
    ).with_structured_output(_BendResult).with_retry(stop_after_attempt=2)

    result: _BendResult = llm.invoke([
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
