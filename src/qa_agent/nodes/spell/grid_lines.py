from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Formwork Grid Lines vs Wandansicht (grid_lines)
Check that grid lines (axis labels / column lines) in the wall formwork Schnitt views match those in the Wandansicht.
Flag any grid line present in the Schnitt but absent from the Wandansicht, or vice versa.
If no Wandansicht is visible on the sheet, add "grid_lines" to not_found.\
"""


def grid_lines_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="grid_lines",
        domain="spell",
        issues_key="spell_issues",
        check_name="Formwork Grid Lines Consistency",
        pass_desc="PASS — grid lines in Schnitt views match Wandansicht.",
        nf_desc="NOT FOUND — Wandansicht absent from sheet.",
        prompt=_PROMPT,
    )
