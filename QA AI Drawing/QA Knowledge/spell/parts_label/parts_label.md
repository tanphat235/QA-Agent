# Parts Label Consistency
> **Domain:** Spelling & Title Block | **Check key:** `parts_label`

## Display Name

Parts Label Consistency

## Pass

PASS — all part label codes in views are present in the schedule table(s) and vice versa.

## Not Found

NOT FOUND — no schedule tables (Einbauteilliste / Montageteilliste) visible on sheet.

## Requires Vision

true

## Description

Cross-reference part label codes between the views (Ansicht, Schnitt, Draufsicht) and the schedule table(s) (Einbauteilliste / Montageteilliste). Flag any label visible in a view but absent from the table, and any table entry with no corresponding label in any view. Does NOT check quantities or counts.

## Check Prompt

CHECK — Parts Label Consistency (parts_label)

Every embedded/mounting part code must appear in BOTH places on this sheet:
  (a) as a row in a schedule table — Einbauteilliste (EBT-Nummer) or Montageteilliste (MT-Nummer), AND
  (b) as at least one part label annotated on a view (Ansicht, Wandansicht, Draufsicht, Schnitt, Detail).
A code present in only ONE of the two places is an ERROR. Existence only — never compare quantities.

Read every code directly from THIS sheet (rendered PDF preferred; extracted text as cross-reference
only). Discard any part codes, EBT-Nummer, or MT-Nummer remembered from any other drawing or run.

NOT FOUND — add "parts_label" to not_found ONLY if NEITHER an Einbauteilliste NOR a
Montageteilliste table is visible on this sheet. Do NOT silently pass.

STEP 1 — BUILD TABLE_NUMBERS
  Locate every schedule table present (Einbauteilliste and/or Montageteilliste — table rows have
  columns like EBT-Nummer/MT-Nummer, Hersteller, Bezeichnung, Menge). Read each table row by row
  and collect every EBT-Nummer / MT-Nummer exactly as printed.
  TABLE_NUMBERS = [all codes collected from the schedule-table rows]

STEP 2 — BUILD VIEW_LABELS
  Scan the geometry of every view: Ansicht, Wandansicht, Draufsicht, every Schnitt section and
  every Detail. Collect every part-label code annotated there, including labels drawn rotated or
  vertical, colour-highlighted revision labels, and any block titled "ROTATED / VERTICAL LABELS".
  For a multiplier prefix take the code after the "x" ("2x00104" → "00104").
  EXCLUDE the schedule-table rows themselves, and all rebar annotations (Pos numbers, "ø", "L=",
  "-M.E.", mesh marks).
  VIEW_LABELS = [every distinct part-label code annotated on the views]

STEP 3 — COMPARE THE TWO SETS (reason silently; exact digit-for-digit)
  Codes match only on their complete, exact digit sequence — 07162 and 07163 are DIFFERENT parts;
  one different digit = a different part. A frequent neighbour code (e.g. dozens of 07163) never
  proves a rarer code (07162) present or absent — check each code on its own digits.
  A. Flag every code in VIEW_LABELS whose exact digits match NO code in TABLE_NUMBERS.
  B. Flag every code in TABLE_NUMBERS whose exact digits match NO code in VIEW_LABELS.
     IMPORTANT: a code's own schedule-table row is NOT a view label. A code that appears only
     inside a schedule table and is annotated on no view MUST be flagged — do not treat the
     digits printed in the table row as a view occurrence.
  A code found in a table AND labelled in ≥1 view is consistent — produce NOTHING for it.

OUTPUT — issues[] contains ONLY confirmed problems, nothing else:
  • One issues[] entry = ONE code and its ONE problem, in ≤ 20 words. Examples:
      "EBT 07162 is in the Einbauteilliste but labelled in no view."
      "Label 04210 appears in Schnitt 1-1 but is in no schedule table."
  • If every code is consistent, issues[] MUST be EMPTY (this check then PASSES).
  • NEVER put any of the following in a description: a scan summary, per-code narration,
    the words "consistent" / "no … issue found" / "Flagging:" / "after full scan",
    reasoning, how you verified, or text about codes that turned out fine.
  • ALWAYS write the full lists into the parts_label debug note:
    "parts_label: TABLE_NUMBERS=[...] | VIEW_LABELS=[...] | missing_label=[...] | not_in_table=[...]"

RULES:
  • A code found in ANY present table satisfies (a); if only one table is present, cross-reference
    against that table only.
  • Do NOT compare quantities or counts — existence only.
  • Do NOT flag rebar Pos numbers or bar annotations.
