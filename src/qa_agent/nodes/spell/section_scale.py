from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Scale Consistency (section_scale)
Compare every explicit scale label (M 1:XX) on views or sections against the title block scale.
Flag any view whose labeled scale clearly differs from the title block value.
Only flag where both scales are simultaneously visible and unambiguously different.\
"""


def section_scale_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="section_scale",
        domain="spell",
        issues_key="spell_issues",
        check_name="Scale Consistency",
        pass_desc="PASS — all view scales consistent with title block.",
        nf_desc="NOT FOUND — no scale labels (M 1:XX) visible on views or title block.",
        prompt=_PROMPT,
    )
