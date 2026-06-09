# Total Mass Arithmetic
> **Domain:** Bending & Schedule | **Check key:** `mass_arithmetic`

## Display Name

Total Mass Arithmetic

## Pass

PASS — sum of row masses matches Gesamtmasse footer.

## Not Found

NOT FOUND — Gesamtmasse footer absent or illegible.

## Description

Check whether the total mass in the Stabliste is correct.

Also Check mass for Mattenstahlliste if available

## Check Prompt

CHECK — Total Mass Arithmetic (mass_arithmetic)
Verify that the Gesamtmasse (grand total mass) at the bottom of the Stabliste equals the sum
of all individual row Masse [kg] values.

Read ONLY from the submitted PDF drawing — do NOT use any values from reference/example images.

PROCEDURE:
  1. Read every row's Masse [kg] value from the Stabliste in the PDF drawing.
  2. Sum them: computed_total = Σ Masse_i
  3. Read the Gesamtmasse [kg] footer value from the same table.
  4. If computed_total == Gesamtmasse → PASS, output nothing for this check.
  5. If computed_total ≠ Gesamtmasse → flag as an error.

If the Mattenstahlliste is also present in the PDF drawing, apply the same check to it independently.

NOT FOUND conditions — add "mass_arithmetic" to not_found (do NOT silently pass) if ANY of:
  • The Stabliste is not visible on the sheet
  • The Gesamtmasse footer is absent or illegible on the only available table

Do NOT flag if individual row values or the Gesamtmasse footer are not clearly readable — skip that table.
