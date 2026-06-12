# Lastausgleichgehänge Note
> **Domain:** Spelling & Title Block | **Check key:** `lastausgleich`

## Display Name

Lastausgleichgehänge Note

## Pass

PASS — Lastausgleichgehänge note status matches the Einbauteilliste RD-type EBT requirements.

## Not Found

NOT FOUND — Einbauteilliste (embedded parts list) not found in the drawing.

## Description

Checks whether the "Lastausgleichgehänge" (load balancing hanger) note is correctly present or absent based on the RD-type EBT entries in the Einbauteilliste:

- If any EBT whose Bezeichnung contains a code like **RD42**, **RD50**, etc. has Menge (quantity) **≥ 4** → the drawing **must** contain the text "Lastausgleichgehänge". FAIL if missing.
- If the maximum RD-type EBT quantity is **< 4** (or no RD-type EBTs exist) → the "Lastausgleichgehänge" note **must not** be present. FAIL if found.

If the Einbauteilliste table is not found in the drawing, the check reports NOT FOUND.
