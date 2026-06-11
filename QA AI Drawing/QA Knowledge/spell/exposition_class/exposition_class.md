# Exposition Class vs Concrete Cover
> **Domain:** Spelling & Title Block | **Check key:** `exposition_class`

## Display Name

Exposition Class vs Concrete Cover

## Pass

PASS — Cmin,dur, ΔCdev and Cv in the title block match the expected values for the declared exposition class (φ10 default, BẢNG 3.1).

## Not Found

NOT FOUND — Exposition class (XC1–XC4) or BETONDECKUNG concrete cover values not found in the drawing.

## Description

Looks up the exposition class (XC1–XC4) from the drawing, then verifies that the three concrete cover values in the title block BETONDECKUNG section match the standard table (BẢNG 3.1, φ10 default):

| Class | Cmin,dur | ΔCdev | Cv  |
|-------|----------|-------|-----|
| XC1   | 20       | 10    | 30  |
| XC2   | 35       | 15    | 50  |
| XC3   | 35       | 15    | 50  |
| XC4   | 40       | 15    | 55  |

Formula: Cv = Cmin,dur + ΔCdev
