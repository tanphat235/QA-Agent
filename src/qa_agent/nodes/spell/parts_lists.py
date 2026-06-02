from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Parts Lists Present (parts_lists)
Verify the sheet contains both:
  • Einbauteilliste (embedded parts list)
  • Montageteilliste (assembly/mounting parts list)
Flag each table that is clearly absent.\
"""


def parts_lists_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="parts_lists",
        domain="spell",
        issues_key="spell_issues",
        check_name="Parts Lists Present",
        pass_desc="PASS — Einbauteilliste and Montageteilliste both present.",
        nf_desc="NOT FOUND — neither Einbauteilliste nor Montageteilliste visible on sheet.",
        prompt=_PROMPT,
    )
