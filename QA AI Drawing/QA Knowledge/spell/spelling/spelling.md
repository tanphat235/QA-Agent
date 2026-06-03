# Spelling Errors
> **Domain:** Spelling & Title Block | **Check key:** `spelling`

## Display Name

Spelling Check

## Pass

PASS — no spelling errors found in drawing text.

## Not Found

NOT FOUND — no readable text found on sheet.

## Description

Check whether all text in the PDF is spelled correctly.

## Check Prompt

CHECK — Spelling Errors (spelling)
Flag clear spelling mistakes in German or English words in titles, labels, notes, callouts, or title block.

Do NOT flag:
  • Person name fields — the following title block fields contain personal names or initials
    which must NEVER be checked for spelling:
      "Drawn By", "Designed By", "Checked By" and their values (e.g. "T.Ng", "H.T", "D.M",
      "-I.T", any initials or abbreviated names). These are not subject to spelling rules.
  • Accepted engineering abbreviations (Ø, typ., M.E., Reinf., Bew., pos.) and capitalization style.
  • Standard German title block labels — these are fixed standard terms, ALWAYS treat as correct:
      "FACHPLANER/PLANERSTELLER", "MTT-Nummer", "BETONDECKUNG", "WANDANSICHT", "BEWEHRUNG",
      "STABLISTE", "MATTENSTAHLLISTE", "EINBAUTEILLISTE", "MONTAGETEILLISTE", "MASSSTAB".
      PDF fonts frequently distort these (e.g. "FACHPLANFR" = "FACHPLANER", "PLANFRSTFLLER" =
      "PLANERSTELLER") — treat any such distorted rendering as correct, do NOT flag it.
  • Any character-level confusion due to compressed PDF fonts:
      E↔F, T↔I, N↔M, rn↔m, 0↔O — if the intended word is a known standard term, treat as correct.
  • Only flag completely wrong words that cannot be explained by font rendering, and that are
    NOT person names and NOT standard engineering/German title block labels.

If no readable text is visible anywhere on the sheet, add "spelling" to not_found.
