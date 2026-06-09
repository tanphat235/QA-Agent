from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Parts Label Consistency (parts_label)

All values used in this check MUST be read directly from this PDF. Discard any part codes,
EBT-Nummer, or MT-Nummer from memory or from any previous drawing run before starting.

NOT FOUND — add "parts_label" to not_found if NEITHER Einbauteilliste NOR Montageteilliste
is visible on this sheet. Do NOT silently pass.

STEP 1 — READ TABLE NUMBERS FROM THIS PDF
  Locate the Einbauteilliste (embedded parts list) and/or Montageteilliste (mounting parts list)
  on this sheet. For each table that is present, read every EBT-Nummer (from Einbauteilliste)
  and every MT-Nummer (from Montageteilliste) row by row directly from the PDF.
  Record the full list: TABLE_NUMBERS = [all EBT-Nummer and MT-Nummer read from this PDF]

STEP 2 — READ VIEW LABELS FROM THIS PDF
  Scan every view on the sheet: Ansicht, Wandansicht, Draufsicht, and every Schnitt section.
  Collect every part label that looks like an EBT-Nummer or MT-Nummer (numeric codes assigned
  to embedded or mounting parts).

STEP 3 — CROSS-REFERENCE
  A. Label not in table: any code in VIEW_LABELS that is NOT in TABLE_NUMBERS → flag as error.
     State which label and which view it appeared in.
  B. Table number not labeled: any EBT-Nummer or MT-Nummer in TABLE_NUMBERS that is NOT found
     in any view after scanning the entire sheet → flag as error.
     State which number and which table it came from.

RULES:
  • Only flag codes confirmed present in your written lists with a clear mismatch.
  • A code found in ANY present table is consistent — do NOT flag it.
  • If only one table is present, cross-reference against that table only.
  • Do NOT compare quantities or counts — existence only.
  • Do NOT flag rebar Pos numbers or bar annotations.\
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
