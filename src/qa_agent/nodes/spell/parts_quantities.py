from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Parts Label Consistency (parts_quantities)
A drawing does NOT need to have both tables — check whichever table(s) are present.
If NEITHER Einbauteilliste NOR Montageteilliste is present, add "parts_quantities" to not_found and skip.

For each table that IS present, cross-reference every part label visible in Schnitt and Ansicht views
against that table:
  1. UNLABELED PARTS — any part belonging to a present table with NO label in the views. Flag each.
  2. LABEL NOT IN TABLE — any label code in the views that cannot be found in any present table. Flag each.
RULES:
  • A label found in ANY present table is consistent — do NOT flag it.
  • Do NOT flag rebar Pos numbers — only flag embedded/mounting part designations.
  • Only flag when you can clearly read the label AND confirm it is absent from all present tables.
  • If only Einbauteilliste is present, only cross-reference against Einbauteilliste.
  • If only Montageteilliste is present, only cross-reference against Montageteilliste.\
"""


def parts_quantities_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="parts_quantities",
        domain="spell",
        issues_key="spell_issues",
        check_name="Parts Label Consistency",
        pass_desc="PASS — all part labels in views match the present schedule table(s).",
        nf_desc="NOT FOUND — no schedule tables (Einbauteilliste / Montageteilliste) visible on sheet.",
        prompt=_PROMPT,
    )
