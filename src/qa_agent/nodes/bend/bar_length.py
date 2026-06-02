from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Review the bar schedule (Stabliste), mesh schedule (Mattenstahlliste), and rebar schemas in this structural drawing.
Report ONLY issues you can directly observe from clearly visible values in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Bar Length vs Schedule (bar_length)
For each rebar schema where a total length L is explicitly shown, compare it with the "Einzel Länge" in the Stabliste.
Flag if the schema length clearly differs from the schedule value.
If the schema total length or Einzel Länge values are not explicitly shown, add "bar_length" to not_found.\
"""


def bar_length_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="bar_length",
        domain="bend",
        issues_key="bend_issues",
        check_name="Bar Length vs Schedule",
        pass_desc="PASS — all schema lengths match Einzel Länge in Stabliste.",
        nf_desc="NOT FOUND — schema total lengths or Einzel Länge values not visible.",
        prompt=_PROMPT,
    )
