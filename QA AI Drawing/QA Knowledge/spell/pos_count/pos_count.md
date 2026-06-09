# Last Position Number vs Title Block
> **Domain:** Spelling & Title Block | **Check key:** `pos_count`

## Display Name

Last Position Number vs Title Block

## Pass

PASS — letzte Stabstahlposition and letzte Mattenposition match schedule tables.

## Not Found

NOT FOUND — 'letzte Stabstahlposition' field not visible in title block.

## Description

Check whether the rebar positions on the drawing (excluding rebar positions greater than 100) match the positions in the detail drawings.

## Check Prompt

CHECK — Last Position Number vs Title Block (pos_count)
The title block contains two fields that declare the last (highest) position number used:
  • "letzte Stabstahlposition" — last regular bar position in the Stabliste
  • "letzte Mattenposition"    — last mesh position in the Mattenstahlliste (if mesh is present)

PROCEDURE for Stabliste:
  1. Scan the Stabliste and find the highest Pos number that is ≤ 99 (ignore Pos 100+ completely).
  2. Read the value in the "letzte Stabstahlposition" field of the title block.
  3. If highest_pos_≤99 == title_block_value → PASS, do NOT flag anything.
  4. If highest_pos_≤99 ≠ title_block_value → flag as an issue.

PROCEDURE for Mattenstahlliste (only if the table is present on the sheet):
  1. Find the highest Pos number listed in the Mattenstahlliste.
  2. Read the value in the "letzte Mattenposition" field of the title block.
  3. If highest_mesh_pos == title_block_value → PASS, do NOT flag anything.
  4. If highest_mesh_pos ≠ title_block_value → flag as an issue.

IMPORTANT:
  • Read ONLY from the submitted PDF drawing — do NOT use any values from reference/example images.
    Any circled numbers or title blocks visible in the reference images are examples only and must
    be completely ignored. Only values in the actual drawing PDF are valid inputs for this check.
  • Read the Stabliste and title block from THE SAME SHEET in the PDF. Do not compare values
    across different sheets or different drawings.
  • The presence of Pos 100, 101, 102, … in the Stabliste is normal and expected.
    These are special accessory bars. They do NOT affect letzte Stabstahlposition at all.
    If the title block value equals the highest regular Pos (≤99), the check PASSES — period.
  • Only flag when the numbers clearly and unambiguously differ on the same sheet.

NOT FOUND conditions — add "pos_count" to not_found (do NOT silently pass) if ANY of:
  • The Stabliste is not visible on the sheet
  • The title block is not visible on the sheet
  • The "letzte Stabstahlposition" field is not visible in the title block

If Mattenstahlliste is absent, skip the mesh part of this check only (do NOT add to not_found for that).
