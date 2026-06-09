# Spacer / Clamp Label Suffix
> **Domain:** Rebar Labels & Dims | **Check key:** `spacer_label`

## Display Name

Spacer / Clamp Label Suffix

## Pass

PASS — all spacer and clamp labels include the "-M.E." suffix.

## Not Found

NOT FOUND — no "-M.E." labels found on sheet to identify spacer/clamp positions.

## Description

Check that the Spacers/Clamps reinforcement label includes the suffix “-M.E.” at the end. Only two types of this rebar is Spacers/Clamps reinforcement

## Check Prompt

CHECK — Spacer / Clamp Label Suffix (spacer_label)
Use the "-M.E." suffix itself to identify which Pos numbers are spacers/clamps, then verify every
label for those positions also carries the suffix.

PROCEDURE — two steps:

  STEP 1 — Identify spacer/clamp positions:
    A Pos number is ONLY the number drawn inside a circle or oval shape in the drawing.
    Numbers that appear without a circle (quantity counts, bar diameters, spacing values) are
    NOT Pos numbers — do NOT use them as Pos identifiers.

    Scan the drawing for labels where a CIRCLED number appears together with "-M.E.":
      • Circled pos before: ⑰ ø 8/45 -M.E.   →  Pos 17 is a spacer
      • Circled pos after:  -M.E. ⑪             →  Pos 11 is a spacer
    Extract ONLY the numbers that are visually enclosed in a circle/oval. These are the spacer Pos.

    CRITICAL — do NOT misread label parts as Pos numbers:
      • In "2x 11 ø 12/15", the "11" is a bar quantity (not circled) → NOT a Pos number
      • In "4 ø 8/45 -M.E.", the "4" is a count (not circled) → NOT a Pos number
      • Only a number inside a drawn circle or oval is a Pos number

  STEP 2 — Check ONLY fully visible section view callouts:
    For every circled Pos identified in Step 1, scan section view callouts in the Schnitt views.
    A callout is only checkable if ALL of the following are true:
      • The full label text is clearly readable (not cut off, not at the drawing edge)
      • The circled Pos number is visible and unambiguous
      • The "-M.E." portion is either present or clearly absent — not just hidden by truncation

    Flag a callout ONLY when it is fully visible and clearly missing "-M.E.".

    STRICTLY EXCLUDED — do NOT check these under any circumstances:
      • Stabliste rows (bar schedule table)
      • Bending schema figures (drawn bar shape with dimension lines and L= label)
      • Any label that appears cut off, truncated, or reaching the edge of the drawing —
        a truncated label (e.g. "17 ø 8/4..." cut off at page edge) is NOT a violation,
        the missing "-M.E." is simply outside the visible area. NEVER flag truncated text.

NOTE — all Pos numbers and examples above are illustrative only.
Read all actual Pos numbers and labels from the PDF drawing being analyzed.
Do NOT use any number from the examples as an actual value.

Do NOT flag Pos numbers that never appear with "-M.E." anywhere — those are not spacers/clamps.
Do NOT flag if you cannot clearly read the full label text.
If no "-M.E." labels are visible anywhere on the sheet, add "spacer_label" to not_found — do NOT silently pass.
