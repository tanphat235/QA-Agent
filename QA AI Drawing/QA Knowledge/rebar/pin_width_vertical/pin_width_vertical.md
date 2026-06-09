# Vertical Pin Width
> **Domain:** Rebar Labels & Dims | **Check key:** `pin_width_vertical`

## Display Name

Vertical Pin Width

## Pass

PASS — all vertical pin widths match wall_width – 2×Cv.

## Not Found

NOT FOUND — wall thickness, concrete cover (Cv), or labeled pin dimension not visible.

## Description

check the width of the horizontal and vertical pin reinforcement.

Vertical pin = wall_width – 2*Cv

Cv value in detail

A vertical pin is a vertically placed pin that is usually shown in the cross-section next to the Bewehrung. In this example, it is rebar position 5.

Width_ver_pin = 30 – 2*2.5 = 25

## Check Prompt

CHECK — Vertical Pin Width (pin_width_vertical)
IDENTIFICATION — where to find the vertical pin schema:
  Look ONLY at the SIDE cross-section of the Bewehrung — the section that shows the wall
  from the side (typically named "Schnitt a-a", but may have another name). This section
  cuts through the wall horizontally and shows the wall thickness in the horizontal direction.

  In that section, the vertical pin bending schema is the U-shaped or rectangular stirrup
  whose short dimension (width) spans across the wall thickness. The width to verify is that
  short horizontal dimension labeled on the schema.

  Do NOT pick up schemas from:
    • The horizontal/bottom cross-section (Schnitt b-b, Schnitt c-c) — those are horizontal pins
    • Any schema whose labeled width is significantly larger than (wall_width – 2×Cv) — those
      are other bar types (hairpins, ties, etc.), not vertical pins

IMPORTANT — EXCLUDE spacers/clamps:
  Any Pos whose label contains "-M.E." is a spacer/clamp, not a pin — skip entirely.

WIDTH FORMULA (use values from STEP A, not the illustration numbers):
  Required width = wall_width – 2 × Cv
  [Formula illustration only — values are not from any real drawing]:
    e.g. if wall_width were 20 cm and Cv were 2.0 cm → required = 20 – 4.0 = 16 cm

  Only check schemas whose labeled width is close to this calculated value (within a few cm).
  If a schema's labeled width is much larger than the required value, it is not a vertical pin — skip it.

Flag if the labeled pin width clearly differs from the required calculated value.

NOT FOUND conditions — add "pin_width_vertical" to not_found (do NOT silently pass) if ANY of:
  • The side section (Schnitt a-a or equivalent) is not visible on the sheet
  • No vertical pin schema (non-spacer U-shape stirrup) is found in the side section
  • wall_width cannot be read from the drawing
  • Cv cannot be read from the BETONDECKUNG table
  • The pin width dimension is not labeled on the schema
