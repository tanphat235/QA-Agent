from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Parts Label Consistency (parts_label)
Verify that every part label code visible in the drawing views exists in the schedule table(s),
and every table entry has at least one corresponding label visible somewhere in the views.
Read ALL part codes, labels, and table entries directly from the submitted PDF drawing.
All part numbers and descriptions in these instructions are examples only — do NOT use memory
or training knowledge about part codes (e.g. "Halfen", "HTA", specific EBT numbers).
Every value used in this check must be visually read from the PDF.

A drawing does NOT need to have both tables — check whichever table(s) are present.
If NEITHER Einbauteilliste NOR Montageteilliste is present, add "parts_label" to not_found and skip.

For each table that IS present, cross-reference every part label visible in Schnitt and Ansicht views
against that table:
  1. LABEL NOT IN TABLE — any label code visible in the views that cannot be found in any present table. Flag each.
  2. TABLE ENTRY NOT LABELED — any part listed in the table with NO corresponding label visible in ANY view
     (check ALL views: Ansicht, Wandansicht, Draufsicht, all Schnitt sections). Flag only when the label
     is absent from every view after scanning the entire sheet.

RULES:
  • Read part codes from the PDF only — do NOT recall part codes from memory or examples.
  • CHECK LABEL EXISTENCE ONLY — do NOT compare quantities.
  • Labels with multiplier prefix (e.g. "2x00104") — extract the part code after the multiplier.
  • A label found in ANY present table is consistent — do NOT flag it.
  • Do NOT flag rebar Pos numbers — only flag embedded/mounting part designations.
  • Only flag when you can clearly read the label AND confirm it is absent from all present tables.
  • If only Einbauteilliste is present, only cross-reference against Einbauteilliste.
  • If only Montageteilliste is present, only cross-reference against Montageteilliste.\
"""


def parts_label_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="parts_label",
        domain="spell",
        issues_key="spell_issues",
        check_name="Parts Label Consistency",
        pass_desc="PASS — all part label codes in views are present in the schedule table(s) and vice versa.",
        nf_desc="NOT FOUND — no schedule tables (Einbauteilliste / Montageteilliste) visible on sheet.",
        prompt=_PROMPT,
    )
