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

All values used in this check MUST be read directly from this PDF / extracted text. Discard any
part codes, EBT-Nummer, or MT-Nummer from memory or from any previous drawing run before starting.

NOT FOUND — add "parts_label" to not_found if NEITHER Einbauteilliste NOR Montageteilliste
is visible on this sheet. Do NOT silently pass.

CRITICAL — EXACT-DIGIT MATCHING (read this before flagging anything):
  • Part codes are full numeric strings (e.g. 5-digit EBT numbers). Codes that differ by even ONE
    digit are DIFFERENT parts — 07162 and 07163 are NOT the same part.
  • A code appearing many times NEVER implies that a similar-looking code is present or absent.
    Each code must be matched on its OWN complete, exact digit sequence. Do not let a frequent
    neighbour code (e.g. dozens of 07163) mask the presence of a rarer one (e.g. 07162).
  • The same view label may be repeated many times, drawn rotated/vertical, or colour-highlighted
    as a revision change. Treat ALL of these as valid occurrences. Scan the WHOLE sheet, including
    any block titled "ROTATED / VERTICAL LABELS".

STEP 1 — READ TABLE NUMBERS FROM THIS PDF
  Locate the Einbauteilliste (embedded parts list) and/or Montageteilliste (mounting parts list).
  For each table present, read every EBT-Nummer / MT-Nummer row by row, exactly as printed.
  TABLE_NUMBERS = [all EBT-Nummer and MT-Nummer read from this PDF]

STEP 2 — READ VIEW LABELS FROM THIS PDF
  Scan every view: Ansicht, Wandansicht, Draufsicht, and every Schnitt section. Collect every
  part-label code (numeric codes for embedded/mounting parts). Skip rebar annotations
  (Pos numbers, "ø", "L=", "-M.E."). For a multiplier prefix (e.g. "2x00104") take the code after "x".
  VIEW_LABELS = [every distinct part-label code found in the views]

STEP 3 — CROSS-REFERENCE (reason SILENTLY; emit only confirmed problems)
  A. Label not in table: a code in VIEW_LABELS whose exact digits match NO table row.
  B. Table number not labelled: for EACH code in TABLE_NUMBERS, search the ENTIRE sheet
     (all views + any rotated/vertical block) for that EXACT digit sequence. It is a problem
     ONLY if the exact code occurs ZERO times anywhere outside the table itself.
     Re-check before deciding: if the exact code appears even once in a view, it is consistent —
     it is NOT a problem. Never infer absence from a code that differs by one or more digits.

  Do ALL of this reasoning silently. A code that exists in a table AND is labelled in ≥1 view
  (or vice-versa) is CONSISTENT — it is not a finding, so produce NOTHING for it.

OUTPUT — issues[] contains ONLY confirmed problems, nothing else:
  • One issues[] entry = ONE code and its ONE problem, in ≤ 20 words. Examples:
      "EBT 07162 is in the Einbauteilliste but labelled in no view."
      "Label 04210 appears in Schnitt 1-1 but is in no schedule table."
  • If every code is consistent, issues[] MUST be EMPTY (this check then PASSES).
  • NEVER put any of the following in a description: a scan summary, per-code narration,
    the words "consistent" / "no … issue found" / "Flagging:" / "after full scan",
    reasoning, how you verified, or text about codes that turned out fine.
  • Put any reasoning/among-codes notes ONLY in the parts_label debug note — never in issues[].

RULES:
  • A code found in ANY present table is consistent — do NOT flag it.
  • If only one table is present, cross-reference against that table only.
  • Do NOT compare quantities or counts — existence only.
  • Do NOT flag rebar Pos numbers or bar annotations.
