# Bending Angle / Mandrel Diameter
> **Domain:** Bending & Schedule | **Check key:** `bending_angle`

## Display Name

Bending Angle / Mandrel Diameter

## Pass

PASS — all labeled mandrel diameters comply with minimum requirements.

## Not Found

NOT FOUND — no labeled mandrel diameters found in schemas.

## Description

Check each rebar schema to verify that the bending angles is correct.

Ø8 bending factor is 4 → dbr = 3.2

Ø10 bending factor is 4 → dbr = 4

Ø12 bending factor is 4 → dbr = 4.8

Ø16 bending factor is 4 → dbr = 6.4

Ø20 bending factor is 7 → dbr = 14

Ø24 bending factor is 7 → dbr = 16.8

Ø28 bending factor is 7 → dbr = 19.6

## Check Prompt

CHECK — Bending Angle / Mandrel Diameter (bending_angle)
For each rebar schema, verify any explicitly labeled mandrel diameter using these minimum values:
  Ø8  → factor 4, min. dbr = 3.2 cm
  Ø10 → factor 4, min. dbr = 4.0 cm
  Ø12 → factor 4, min. dbr = 4.8 cm
  Ø16 → factor 4, min. dbr = 6.4 cm
  Ø20 → factor 7, min. dbr = 14.0 cm
  Ø24 → factor 7, min. dbr = 16.8 cm
  Ø28 → factor 7, min. dbr = 19.6 cm
Flag if a labeled mandrel diameter in the schema is clearly below the minimum for that bar size.
Do NOT flag unlabeled bending radii or diameters.
