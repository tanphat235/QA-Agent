from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Section Name Completeness (section_name)
Identify all section cut designations called out in the Ansicht or Bewehrung (e.g. "1-1", "2-2", "3-3").
Verify that a corresponding view with the same designation number is present on the sheet.
A view satisfies the requirement if it is labeled "Schnitt X-X", "Draufsicht X-X", or any other
view type (top view, cross-section, detail) that carries the same designation number X-X.
Flag only if NO view of any type with that designation number exists anywhere on the sheet.
Do NOT flag if the view exists but is located elsewhere on the sheet.\
"""


def section_name_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="section_name",
        domain="spell",
        issues_key="spell_issues",
        check_name="Section Name Completeness",
        pass_desc="PASS — all section cuts in Ansicht/Bewehrung have a corresponding Schnitt view.",
        nf_desc="NOT FOUND — no section cut designations found in Ansicht or Bewehrung.",
        prompt=_PROMPT,
    )
