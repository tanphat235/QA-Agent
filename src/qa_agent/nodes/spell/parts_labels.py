from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Part Labels in Views (parts_labels)
Check that every part listed in any present table has an explicit label in the section/elevation views.
A drawing does NOT need both tables — check whichever table(s) are present.
If NEITHER table is present, add "parts_labels" to not_found and skip.

For Einbauteilliste (built-in parts / Einbauteile) — if this table is present:
  Count all built-in parts visible in Schnitt and Ansicht views.
  Verify each part has an explicit label (position number or designation) shown directly adjacent
  or via leader line. Flag any Einbauteil shown in the views without a label.

For Montageteilliste (mounting parts / Montageteile) — if this table is present:
  Count all mounting parts visible in Schnitt and Ansicht views.
  Verify each part has an explicit label shown directly adjacent or via leader line.
  Flag any Montageteil shown in the views without a label.\
"""


def parts_labels_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="parts_labels",
        domain="spell",
        issues_key="spell_issues",
        check_name="Part Labels in Views",
        pass_desc="PASS — all parts from present table(s) are labeled in section/elevation views.",
        nf_desc="NOT FOUND — no schedule tables (Einbauteilliste / Montageteilliste) visible on sheet.",
        prompt=_PROMPT,
    )
