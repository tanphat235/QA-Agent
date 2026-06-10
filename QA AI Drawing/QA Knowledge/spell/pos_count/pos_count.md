# Last Position Number vs Title Block
> **Domain:** Spelling & Title Block | **Check key:** `pos_count`

## Display Name

Last Position Number vs Title Block

## Pass

PASS — letzte Stabstahlposition and letzte Mattenposition match schedule tables.

## Not Found

NOT FOUND — neither 'letzte Stabstahlposition' nor 'letzte Mattenposition' visible in title block.

## Description

Check that the last position numbers declared in the title block match the actual highest Pos numbers found in the schedule tables on the same sheet.

## Check Prompt

CHECK pos_count — Last Position Number vs Title Block

1. Search the PDF for the labels "letzte Stabstahlposition" and "letzte Mattenposition".

2. For each label found, extract the position number located immediately next to it.
   The number is displayed inside a circle (for Stabstahlposition) or a square (for Mattenposition).
   Use the visually associated number nearest to the label when multiple numbers are present.
   Accept minor OCR variations in the label text.
   → Save as: pos_count_title_stab / pos_count_title_matten (null if label absent or shape empty)

3. Search for the schedule tables "Stabliste" and "Mattenstahlliste".

4. In "Stabliste": collect all Pos numbers. Ignore any Pos ≥ 100 (special accessory bars).
   Find the maximum remaining Pos number.
   → Save as: pos_count_max_stab (null if table absent)

5. In "Mattenstahlliste": collect all Pos numbers. Ignore any Pos ≥ 100.
   Find the maximum remaining Pos number.
   → Save as: pos_count_max_matten (null if table absent)

6. Report all four values in the dedicated output fields. Do NOT add pos_count to the issues list.
   Add "pos_count" to not_found only if BOTH pos_count_title_stab AND pos_count_title_matten are null.
