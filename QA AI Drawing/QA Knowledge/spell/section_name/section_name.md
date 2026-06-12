# Section Name Completeness
> **Domain:** Spelling & Title Block | **Check key:** `section_name`

## Display Name

Section Name Completeness

## Pass

PASS — all section cuts in Ansicht/Bewehrung have a corresponding Schnitt view.

## Not Found

NOT FOUND — no section cut designations found in Ansicht or Bewehrung.

## Description

Check that section markers and section views are consistent in both directions:
every section marker shown in Ansicht/Bewehrung must have a corresponding section view, and every section view must have a corresponding section marker.

## Check Prompt

CHECK — Section Name Completeness (section_name)

DEFINITIONS:
  Section marker — a cutting-plane arrow or triangle symbol drawn inside an Ansicht or Bewehrung
                   view. The designation label (a number or letter) is printed directly beside or
                   below the marker symbol. Read the label from its spatial position next to the
                   symbol — do NOT invent or assume designations.
  Section view   — a view title on the sheet that begins with "Schnitt" or "Draufsicht" followed
                   by a designation (e.g. "Schnitt a-a M 1:25", "Draufsicht b-b M 1:10").
                   Both Schnitt and Draufsicht are fully valid and must not be flagged for the
                   view type alone.

STEP 1 — Collect section markers from Ansicht and Bewehrung:
  Scan every cutting-plane symbol visible in the Ansicht and Bewehrung views.
  For each symbol, read the label printed immediately beside or below it.
  Record only labels you can directly observe — do not guess or fill in missing ones.
  MARKERS = list of designations read from the drawing.

STEP 2 — Collect all Schnitt and Draufsicht view titles from the sheet:
  Scan the entire sheet for view titles beginning with "Schnitt" or "Draufsicht".
  Record the full designation of each title you find.
  VIEWS = list of designations read from the drawing.

STEP 3 — Cross-check both directions, one error item per issue:
  A) For each designation in MARKERS:
     If no entry in VIEWS carries the same designation → flag as error.

  B) For each designation in VIEWS:
     If no section marker in MARKERS carries the same designation → flag as error.

OUTPUT RULES:
  • Do ALL cross-checking and re-verification silently BEFORE writing any output.
  • Output an item ONLY for a designation that still has no counterpart after re-checking.
    If a suspected mismatch resolves on re-check, output NOTHING for it.
  • NEVER narrate the verification process. The description must not contain phrases like
    "matched", "re-evaluating", "cross-checking confirms", "after full review", or lists of
    pairs that are correct.
  • One error item per unmatched designation. Description format:
    "Section marker 'x-x' has no corresponding Schnitt/Draufsicht view" or
    "View 'Schnitt x-x' has no corresponding section marker".
  • Use only designations actually read from the drawing in descriptions.
  • All matched pairs → mention them ONLY in debug_notes, never in issues.

NOT FOUND — add "section_name" to not_found if:
  • The Ansicht or Bewehrung area is not visible on the sheet, OR
  • No markers AND no Schnitt/Draufsicht titles can be found at all
