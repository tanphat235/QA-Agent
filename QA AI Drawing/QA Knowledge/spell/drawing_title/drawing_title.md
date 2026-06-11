# Drawing Title vs Title Block
> **Domain:** Spelling & Title Block | **Check key:** `drawing_title`

## Display Name

Drawing Title vs Title Block

## Pass

PASS — Drawing Title matches the Title Block field in either German or English.

## Not Found

NOT FOUND — Drawing Title or Drawing No. field is empty or not found in the title block.

## Description

Check whether the Drawing Title and Drawing No. are present and match the drawing name at the top of the sheet.

## Check Prompt

CHECK drawing_title — Drawing Title, Drawing No., and Drawing Name consistency

PRE-EXTRACTED VALUES:
  The section "=== PRE-EXTRACTED TITLE BLOCK VALUES (from coordinate analysis) ===" in the
  drawing text contains the exact values already extracted by coordinate analysis.
  Use ONLY these pre-extracted values for this check. Do NOT search the raw drawing text
  for these fields yourself — the coordinate extraction is more accurate than text scanning.

  The section contains:
    Drawing Title: <value or "(empty)">
    Drawing No.:   <value or "(empty)">
    Drawing Name (top of sheet): <value or "(not found)">

1. Read "Drawing Title" from the PRE-EXTRACTED section:
   If the value is "(empty)" → add "drawing_title" to not_found and stop all remaining steps.
   The value may contain two lines: one German (TITLE_DE) and one English (TITLE_EN).

2. Read "Drawing No." from the PRE-EXTRACTED section:
   If the value is "(empty)" → add "drawing_title" to not_found and stop all remaining steps.

3. Drawing Title language check (only if both TITLE_DE and TITLE_EN are present):
   Compare by meaning. Acceptable differences: language, capitalization, punctuation, abbreviations.
   Flag as error if they refer to different elements, axes, levels, or drawing types.

4. Drawing Name extraction:
   Read "Drawing Name (top of sheet)" from the PRE-EXTRACTED section.
   If "(not found)" → skip step 5.

5. Drawing Name vs Drawing Title:
   Compare drawing_name with the Drawing Title value (either language line).
   Semantic comparison only — ignore language, capitalization, spacing.
   If same drawing → PASS. If clearly different → flag as error.

NOT FOUND — add "drawing_title" to not_found if:
  • "Drawing Title" value is "(empty)", OR
  • "Drawing No." value is "(empty)"
