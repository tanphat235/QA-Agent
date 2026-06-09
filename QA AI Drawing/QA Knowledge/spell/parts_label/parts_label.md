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

## Reference Images

![Parts Label Consistency example 1](./img_001.png)

## Check Prompt

CHECK — Parts Label Consistency (parts_label)
Verify that every part label code visible in the drawing views exists in the schedule table(s),
and every table entry has at least one corresponding label visible somewhere in the views.
Read ALL part codes, labels, and table entries directly from the submitted PDF drawing.
All part numbers and descriptions in these instructions are examples only — do NOT use memory
or training knowledge about part codes (e.g. "Halfen", "HTA", specific EBT numbers).
Every value used in this check must be visually read from the PDF.

A drawing does NOT need to have both tables — check whichever table(s) are present.

NOT FOUND conditions — add "parts_label" to not_found (do NOT silently pass) if ANY of:
  • Neither Einbauteilliste NOR Montageteilliste is visible on the sheet
  • The table area is not legible enough to read part codes
  • The Ansicht and Schnitt views are not visible or not legible

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
  • If only Montageteilliste is present, only cross-reference against Montageteilliste.
