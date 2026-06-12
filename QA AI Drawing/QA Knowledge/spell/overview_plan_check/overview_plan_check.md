# Overview Plan vs Title Block
> **Domain:** Spelling & Title Block | **Check key:** `overview_plan_check`

## Display Name

Overview Plan vs Title Block

## Pass

PASS — Element data in title block matches the overview plan statistics table.

## Not Found

NOT FOUND — Overview plan not uploaded, or element not found in the statistics table.

## Description

Compares the element data in the drawing title block against the corresponding row in the overview plan statistics table (Stückliste / Elementliste).

**Step 1 — Element identification:**
Extract the element code from the drawing title (e.g. "Pr.- TT-Plate-202-850" → code "202-850") and the Drawing No. from the title block (e.g. "FRA31-LUP-ZZ-03-DR-S-8850"). The matching row in the overview plan is found by Drawing No. (primary) or element code (fallback).

**Step 2 — Fields compared:**

| Title block field | Overview plan column | Tolerance |
|---|---|---|
| Volumen / Volume (m³) | volume | ±0.001 m³ |
| Gewicht / Weight (to) | weight | ±0.001 to |
| Anzahl / Quantity | quantity | exact |
| Drawing No. / Plan-Nr. | drawing_no | exact |

Any mismatch raises an error. If the element is not found in the overview plan table, the check reports NOT FOUND.

This check is only active when an Overview Plan PDF has been uploaded as a supplementary file.
