from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Component Name vs Title Block (component_name)
Verify the component/element name on the Wandansicht matches the drawing name in the title block.
Flag only where BOTH are visible and they clearly differ.
If only one of the two (Wandansicht label or title block name) is visible, add "component_name" to not_found.\
"""


def component_name_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="component_name",
        domain="spell",
        issues_key="spell_issues",
        check_name="Component Name vs Title Block",
        pass_desc="PASS — Wandansicht component name matches title block.",
        nf_desc="NOT FOUND — Wandansicht element label or title block name not visible.",
        prompt=_PROMPT,
    )
