# Exposition Class vs Concrete Cover
> **Domain:** Spelling & Title Block | **Check key:** `exposition_class`

## Display Name

Exposition Class vs Concrete Cover

## Pass

PASS — Cmin,dur, ΔCdev and Cv in the title block match Table 3.1 for the declared exposition class at the selected rebar diameter.

## Not Found

NOT FOUND — Exposition class (XC1–XC4) or BETONDECKUNG concrete cover values not found in the drawing.

## Rebar Diameter

10

## Description

Looks up the exposition class (XC1–XC4) from the drawing, then verifies the three concrete cover values in the title block BETONDECKUNG section against Table 3.1.

The expected values depend on the rebar diameter selected for this check (Ø10 by default — change it in Define Rules to compare against another column):

- Cmin,dur = the c_nom cell for the selected diameter
- ΔCdev = Δc of the class (same for every diameter)
- Cv = Cmin,dur + ΔCdev

Table 3.1 — concrete cover, carbonation-induced corrosion (c_nom [mm] per diameter):

| Class | c_min | Δc | Ø6 | Ø8 | Ø10 | Ø12 | Ø14 | Ø16 | Ø20 | Ø25 | Ø28 |
|-------|-------|----|----|----|-----|-----|-----|-----|-----|-----|-----|
| XC1   | 10    | 10 | 20 | 20 | 20  | 22  | 24  | 26  | 30  | 35  | 38  |
| XC2   | 20    | 15 | 35 | 35 | 35  | 35  | 35  | 35  | 35  | 40  | 43  |
| XC3   | 20    | 15 | 35 | 35 | 35  | 35  | 35  | 35  | 35  | 40  | 43  |
| XC4   | 25    | 15 | 40 | 40 | 40  | 40  | 40  | 40  | 40  | 40  | 43  |

Example — XC1 at Ø10: Cmin,dur = 20, ΔCdev = 10, Cv = 30. The same class at Ø25: Cmin,dur = 35, ΔCdev = 10, Cv = 45.
