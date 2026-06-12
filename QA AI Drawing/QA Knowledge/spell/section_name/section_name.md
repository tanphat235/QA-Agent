# Section Name Completeness
> **Domain:** Spelling & Title Block | **Check key:** `section_name`

## Display Name

Section Name Completeness

## Pass

PASS — all section cuts in Ansicht/Bewehrung have a corresponding Schnitt view.

## Not Found

NOT FOUND — no section cut designations found in Ansicht or Bewehrung.

## Description

Check that every section marker shown in Ansicht/Bewehrung has a corresponding section view title (Schnitt/Section or Draufsicht/Top view, German-only or bilingual).

## Check Prompt

CHECK — Section Name Completeness (section_name)

DEFINITIONS:
  Section marker — a cutting-plane arrow or triangle symbol drawn inside an Ansicht or Bewehrung
                   view. The designation label (a number or letter) is printed directly beside or
                   below the marker symbol. Read the label from its spatial position next to the
                   symbol — do NOT invent or assume designations.
  Section view   — a view title on the sheet containing "Schnitt" or "Draufsicht" followed by
                   a designation. ALL title formats are equally valid:
                     "Schnitt a-a M 1:25"                        (German only)
                     "Schnitt a-a / Section a-a M 1:25"          (bilingual)
                     "Draufsicht c-c / Top view c-c M 1:25"      (bilingual Draufsicht)
                   Both Schnitt and Draufsicht are fully valid and must not be flagged for the
                   view type or the language format alone.

STEP 1 — Collect section markers from Ansicht and Bewehrung:
  Scan every cutting-plane symbol visible in the Ansicht and Bewehrung views.
  For each symbol, read the label printed immediately beside or below it.
  Marker labels may appear as 'a-a', 'a a', or two separate single letters 'a' ... 'a'
  at the two ends of the cutting line — all of these mean designation 'a-a'.
  Record only labels you can directly observe — do not guess or fill in missing ones.
  MARKERS = list of designations read from the drawing.

STEP 2 — Collect all Schnitt and Draufsicht view titles from the sheet:
  Scan the entire sheet for view titles containing "Schnitt" or "Draufsicht".
  Record the designation of each title you find (from either the German or English part).
  VIEWS = list of designations read from the drawing.

STEP 3 — Cross-check ONE direction only (marker → view):
  For each designation in MARKERS:
     If no entry in VIEWS carries the same designation → flag as error.
     A view title satisfies the marker if the designation appears in ANY part of the
     title, German or English ("Schnitt a-a", "Section a-a", "Draufsicht a-a", ...).

  Do NOT check the reverse direction. A view title with no readable marker is NOT an
  error — marker labels are tiny single letters that often cannot be reliably read
  from extracted text. As long as the view title "Schnitt X-X" / "Draufsicht X-X"
  exists, the view itself is always acceptable.

OUTPUT RULES:
  • Do ALL cross-checking and re-verification silently BEFORE writing any output.
  • Output an item ONLY for a designation that still has no counterpart after re-checking.
    If a suspected mismatch resolves on re-check, output NOTHING for it.
  • NEVER narrate the verification process. The description must not contain phrases like
    "matched", "re-evaluating", "cross-checking confirms", "after full review", or lists of
    pairs that are correct.
  • One error item per unmatched designation. Description format:
    "Section marker 'x-x' has no corresponding Schnitt/Draufsicht view".
  • NEVER output an error about a view title missing its marker — that direction
    is not checked.
  • Use only designations actually read from the drawing in descriptions.
  • All matched pairs → mention them ONLY in debug_notes, never in issues.

NOT FOUND — add "section_name" to not_found if:
  • The Ansicht or Bewehrung area is not visible on the sheet, OR
  • No markers AND no Schnitt/Draufsicht titles can be found at all
