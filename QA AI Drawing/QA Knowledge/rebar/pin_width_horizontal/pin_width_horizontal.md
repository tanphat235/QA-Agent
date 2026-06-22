# Horizontal Pin Width
> **Domain:** Rebar Labels & Dims | **Check key:** `pin_width_horizontal`

## Display Name

Horizontal Pin Width

## Pass

PASS — all horizontal pin widths match wall_width – 2×Cv – 2×Ø_layer1.

## Not Found

NOT FOUND — wall thickness, Cv, outer rebar diameter, or labeled pin dimension not visible.

## Requires Vision

true

## Description

Horizontal pin = wall_width – 2*Cv – 2*Layer1 rebar diameter (round down)

Cv value in detail

A horizontal pin is a horizontally placed pin that is usually shown in the bottom cross-section of the Bewehrung. In this example, it is rebar position 4.

Layer1 rebar diameter detect the label in the side section of the wall (example is position 12)

Width_hor_pin = 30 – 2*2.5 – 2*1.2 = 22.6 ~ 22

## Check Prompt

CHECK — Horizontal Pin Width (pin_width_horizontal)
See the reference image for an example of what a horizontal pin looks like (e.g. Pos 4 in the image).

IDENTIFICATION — how to find the horizontal pin:
  1. Locate the horizontal cross-section BELOW the main Bewehrung section — typically "Schnitt b-b"
     (may have a different label). This section shows the wall from above, cut horizontally.

  2. In that section, find the bending schema that is a plain rectangular U-shape or closed
     rectangular stirrup 
     The connecting bar (the short side) spans the wall thickness — that dimension is the width to check.
     The schema should look like the Pos 4 example in the reference image.

  3. The required width = wall_width – 2×Cv – 2×Ø_layer1 ≈ a few centimeters less than wall_width.
     The horizontal pin schema width should be close to this value.

STRICTLY EXCLUDE — these are NOT horizontal pins:
  • Any schema with angled or non-90° bends (e.g. 110° hooks, diagonal legs) — skip entirely.
  • Any Pos whose label contains "-M.E." — that is a spacer/clamp, not a pin.
  • Any schema from the side section (Schnitt a-a) — those are vertical pins.
  • Any schema whose labeled width is far larger than the required calculated value — wrong element type.

WIDTH FORMULA (use values from STEP A, not the illustration numbers):
  Required width = wall_width – 2 × Cv – 2 × Ø_layer1   (round down to nearest mm)
  [Formula illustration only — values are not from any real drawing]:
    e.g. if wall_width=20 cm, Cv=2.0 cm, Ø_layer1=1.0 cm → 20 – 4.0 – 2.0 = 14 cm

Flag if the labeled pin width clearly differs from the required calculated value.

NOT FOUND conditions — add "pin_width_horizontal" to not_found (do NOT silently pass) if ANY of:
  • The horizontal section (Schnitt b-b or equivalent) is not visible on the sheet
  • No horizontal pin schema (straight 90° rectangular stirrup) is found in that section
  • wall_width cannot be read from the drawing
  • Cv cannot be read from the BETONDECKUNG table
  • Ø_layer1 cannot be read from the side section (Schnitt a-a)
  • The pin width dimension is not labeled on the schema
