# Exposition Class vs Concrete Cover
> **Domain:** Spelling & Title Block | **Check key:** `exposition_class`

## Display Name

Exposition Class vs Concrete Cover

## Pass

PASS — Cmin,dur, ΔCdev and Cv in the title block match Table 3.1 for the governing exposition class at the selected rebar diameter.

## Not Found

NOT FOUND — No exposition class the table covers, or no BETONDECKUNG concrete cover values, found in the drawing.

## Rebar Diameter

10

## Description

Reads the exposition classes off the drawing, then verifies the three concrete cover values in the title block BETONDECKUNG section against Table 3.1.

**Reading the drawing.** The three cover values are read from the column each header stands over — the BETONDECKUNG cell is a three-column table with `Cmin,dur | ΔCdev | Cv` in one row and their values in the row beneath. A sheet frequently carries the same title block twice, the filled-in one and a blank second copy, so every occurrence is tried and the first complete row wins.

**Which class governs.** A drawing commonly names more than one class — `Expositionsklassen: XC1, XD1`. Each states a cover the element must reach, and meeting the strictest meets the rest, so the comparison is made against the class demanding the largest c_nom at the selected diameter. A chloride class (XD, XS) therefore outranks a carbonation class (XC). The finding names the governing class and lists the others.

The expected values depend on the rebar diameter selected for this check (Ø10 by default — change it in Define Rules to compare against another column):

- Cmin,dur = the c_nom cell for the selected diameter
- ΔCdev = Δc of the class (same for every diameter)
- Cv = Cmin,dur + ΔCdev

Table 3.1 — c_nom [mm] per diameter:

*Corrosion of reinforcement by induced carbonation*

| Class | c_min | Δc | Ø6 | Ø8 | Ø10 | Ø12 | Ø14 | Ø16 | Ø20 | Ø25 | Ø28 |
|-------|-------|----|----|----|-----|-----|-----|-----|-----|-----|-----|
| XC1   | 10    | 10 | 20 | 20 | 20  | 22  | 24  | 26  | 30  | 35  | 38  |
| XC2   | 20    | 15 | 35 | 35 | 35  | 35  | 35  | 35  | 35  | 40  | 43  |
| XC3   | 20    | 15 | 35 | 35 | 35  | 35  | 35  | 35  | 35  | 40  | 43  |
| XC4   | 25    | 15 | 40 | 40 | 40  | 40  | 40  | 40  | 40  | 40  | 43  |

*Corrosion of reinforcement by induced chlorides* — one c_nom for every diameter

| Class | c_min | Δc | c_nom (all Ø) |
|-------|-------|----|---------------|
| XD1   | 40    | 15 | 55            |
| XD2   | 40    | 15 | 55            |
| XD3   | 40    | 15 | 55            |

*Corrosion of reinforcement by induced chlorides from sea water* — one c_nom for every diameter

| Class | c_min | Δc | c_nom (all Ø) |
|-------|-------|----|---------------|
| XS1   | 40    | 15 | 55            |
| XS2   | 40    | 15 | 55            |
| XS3   | 40    | 15 | 55            |

Examples:

- XC1 at Ø10 — Cmin,dur = 20, ΔCdev = 10, Cv = 30. The same class at Ø25 — Cmin,dur = 35, ΔCdev = 10, Cv = 45.
- `XC1, XD1` at any diameter — XD1 governs: Cmin,dur = 55, ΔCdev = 15, Cv = 70.

The abrasion classes XM1–XM3 are not compared. They raise c_min by 5 / 10 / 15 mm rather than stating a c_nom of their own ("Concrete cover depends on the exposure class"), so they modify whichever class governs instead of competing with it.
