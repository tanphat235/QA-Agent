# Parts Label Consistency
> **Domain:** Spelling & Title Block | **Check key:** `parts_label`

## Display Name

Parts Label Consistency

## Pass

PASS — all part label codes in views are present in the schedule table(s) and vice versa.

## Not Found

NOT FOUND — no schedule tables (Einbauteilliste / Montageteilliste) visible on sheet.

## Description

Cross-reference part label codes between the views (Ansicht, Schnitt, Draufsicht) and the schedule table(s) (Einbauteilliste / Montageteilliste). Flag any label visible in a view but absent from the table, and any table entry with no corresponding label in any view. Does NOT check quantities or counts.

## Check Prompt

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
  to embedded or mounting parts). Skip rebar annotations (Pos numbers, "ø", "L=", "-M.E.").
  For labels with a multiplier prefix (e.g. "2x00104") take the code after "x": "00104".
  Record the full list: VIEW_LABELS = [all part label codes read from views in this PDF]

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
  • Do NOT flag rebar Pos numbers or bar annotations.
  • Output an item ONLY for a code that still has no counterpart after cross-check.
    If a suspected mismatch resolves, output NOTHING for that code.
  • Never include verification steps, re-checking notes, or pass/fail verdicts in descriptions.
