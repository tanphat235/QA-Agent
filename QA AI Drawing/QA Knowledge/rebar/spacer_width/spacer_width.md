# Spacer / Clamp Width
> **Domain:** Rebar Labels & Dims | **Check key:** `spacer_width`

## Display Name

Spacer / Clamp Width

## Pass

PASS — all spacer/clamp widths match wall_width – 2×Cv + 2×Ø_spacer.

## Not Found

NOT FOUND — wall thickness, Cv, or spacer wire diameter not visible.

## Description

check the width of the Spacers/Clamps reinforcement.

Spacers/Clamps = wall_width – 2*Cv – 2*Spacer diameter (round up)

Cv value in detail

Layer1 rebar diameter detect the label in the side section of the wall (example is position 12)

Width_hor_pin = 30 – 2*2.5 + 2*0.8 = 26.6 ~ 27

## Reference Images

![Spacer / Clamp Width example 1](./img_001.png)

## Check Prompt

CHECK — Spacer / Clamp Width (spacer_width)
For each spacer or clamp element, verify its width using values from STEP A:
  Required width = wall_width – 2 × Cv + 2 × Ø_spacer   (round up to nearest mm)
  where Ø_spacer = physical diameter of the spacer/clamp wire, read from its label in this drawing.
  [Formula illustration only — values are not from any real drawing]:
    e.g. if wall_width=20, Cv=2.0, Ø_spacer=0.6 → 20 – 4.0 + 1.2 = 17.2 → 18 cm

Flag if the labeled spacer/clamp width clearly differs from the calculated value.
If any required dimension (wall_width, Cv, or Ø_spacer) cannot be found, add "spacer_width" to not_found.
