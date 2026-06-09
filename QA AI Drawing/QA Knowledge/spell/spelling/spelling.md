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
Scan all visible text across the entire drawing sheet and report:
  1. Clear spelling mistakes in German or English words
  2. Overlapping or unreadable text

SCAN TARGETS — check all of the following:
  • Title block fields and labels
  • View titles (Schnitt, Ansicht, Draufsicht, Detail, etc.)
  • Callout annotations and notes
  • Table headers and cell content
  • Dimension labels and legend text

SPELLING — flag any word that is clearly misspelled in German or English.
  Acceptable: standard engineering abbreviations (Ø, typ., M.E., Reinf., Bew., Pos.),
  German compound words, accepted acronyms, and capitalization style differences.

TEXT QUALITY — flag any text that is:
  • Overlapping with another text or line element, making it unreadable
  • Truncated or clipped by a view border so the full content cannot be determined
  • Rendered so small or compressed that individual characters cannot be identified

DO NOT flag:
  • Person name fields: "Drawn By", "Designed By", "Checked By" and their values
    (initials, abbreviated names such as "T.Ng", "H.T", "D.M") — these are never spelling errors.
  • PDF font rendering artifacts where the overall word is still identifiable
    (e.g. a colon rendered as a period in a scale label, or slightly compressed letter spacing).

NOT FOUND — add "spelling" to not_found only if no readable text is visible anywhere on the sheet.
