# Spelling Check

> **Domain:** spell | **Check key:** `spelling`

## Display Name

Spelling Check

## Pass

PASS — no spelling or language errors found in drawing text.

## Not Found

NOT FOUND — no readable text found on sheet.

## Description

Identify the language the drawing is written in, then check that all text is spelled correctly and written in that same language.

## Check Prompt

CHECK — Spelling Errors (spelling)
Scan all visible text across the entire drawing sheet and report:
  1. Clear spelling mistakes in the drawing's language
  2. Text written in a language other than the drawing's language
  3. Overlapping or unreadable text

SCAN TARGETS — check all of the following:
  • Title block fields and labels
  • View titles (Schnitt, Ansicht, Draufsicht, Detail, etc.)
  • Callout annotations and notes
  • Table headers and cell content
  • Dimension labels and legend text

STEP 1 — DRAWING LANGUAGE
  Establish the one language the sheet is written in before judging any word.
  If a "DRAWING LANGUAGE CONTEXT" block appears in this prompt, that detected language is
  the sheet's language — keep it unless the readable text plainly contradicts it,
  and if you do overrule it, say which language you used and why in the debug note.
  If no such block appears, read the language off the sheet yourself: use the
  title block labels, view titles and note text, not isolated words.

STEP 2 — SPELLING — flag any word that is clearly misspelled in that language.
  Acceptable: standard engineering abbreviations (Ø, typ., M.E., Reinf., Bew., Pos.),
  German compound words, accepted acronyms, and capitalization style differences.

STEP 3 — LANGUAGE CONSISTENCY — flag readable text written in any language other
  than the drawing's language. A word correctly spelled in the wrong language is
  still an error. Example: on a German sheet, the view title "Formwork and
  reinforcement" or the table header "Quantity" is an error; expected are
  "Schalung und Bewehrung" and "Anzahl".
  For each item, name the offending text, the language it is in, and where it sits.
  Severity "error" for a foreign-language label, title, table header or note;
  severity "warning" for a single foreign word inside an otherwise correct phrase.

  DO NOT flag as a language error:
    • Words spelled identically in both languages (Detail, Plan, Index, Position,
      Total, Material, Beton/beton, Montage, Element, Profil, Standard, Status).
    • Technical abbreviations, unit symbols and codes (mm, cm, kg, m³, Ø, M 1:25,
      C40/50, B500B, XC1, EN 1992, DIN, SIA, ÖNORM, ISO).
    • Proper nouns: company, project, site, city and person names, software or
      plotter footer text, drawing and part numbers, axis and grid labels.
    • Loan words that are standard in the drawing's own language.
    • A sheet that is systematically bilingual by design — where the title block
      labels are paired in two languages throughout. Report that as ONE warning
      describing the bilingual layout, not one item per word.
  Group repeated occurrences of the same foreign phrase into a single item.

STEP 4 — TEXT QUALITY — flag any text that is:
  • Overlapping with another text or line element, making it unreadable
  • Truncated or clipped by a view border so the full content cannot be determined
  • Rendered so small or compressed that individual characters cannot be identified

DO NOT flag:
  • Person name fields: "Drawn By", "Designed By", "Checked By" and their values
    (initials, abbreviated names such as "T.Ng", "H.T", "D.M") — these are never spelling
    or language errors.
  • PDF font rendering artifacts where the overall word is still identifiable
    (e.g. a colon rendered as a period in a scale label, or slightly compressed letter spacing).
  • Garbled or meaningless strings from PDF text extraction — especially in the
    "ROTATED / VERTICAL LABELS" section. These are extraction artifacts, not drawing defects.
    If extracted text looks like random fragments (e.g. "wi4", "nn33", "@4.ll8"), ignore them.
    Never call a fragment a foreign-language word — a foreign-language item requires a
    readable word or phrase you can quote in full.
  • Missing umlauts or accents in extracted text ("Prufung" for "Prüfung", "Traeger" for
    "Träger") — that is an extraction artifact, not a spelling or language error.

NOT FOUND — add "spelling" to not_found only if no readable text is visible anywhere on the sheet.
