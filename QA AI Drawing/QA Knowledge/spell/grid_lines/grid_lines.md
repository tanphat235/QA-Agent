# Formwork Grid Lines Consistency
> **Domain:** Spelling & Title Block | **Check key:** `grid_lines`

## Display Name

Formwork Grid Lines Consistency

## Pass

PASS — grid lines in Schnitt views match Wandansicht.

## Not Found

NOT FOUND — Wandansicht absent from sheet.

## Description

Check whether the wall formwork Schnitt grid lines match the Wandansicht.

## Reference Images

![Formwork Grid Lines Consistency example 1](./img_001.png)

## Check Prompt

CHECK — Formwork Grid Lines vs Wandansicht (grid_lines)
Read all grid line labels and axis numbers directly from the submitted PDF drawing.
All axis names and view names in these instructions are examples only — do NOT use them as actual values.

Check that grid lines (axis labels / column lines) in the wall formwork Schnitt views match those
in the Wandansicht. Flag any grid line present in the Schnitt but absent from the Wandansicht,
or vice versa. Only flag discrepancies that are clearly visible and unambiguous.

NOT FOUND conditions — add "grid_lines" to not_found (do NOT silently pass) if ANY of:
  • No Wandansicht view is visible on the sheet
  • No Schnitt (formwork cross-section) views are visible on the sheet
  • No grid line or axis labels are readable in either the Wandansicht or the Schnitt views
  • The sheet content is too illegible to identify grid line labels
