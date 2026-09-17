# Lastausgleichgehänge Note
> **Domain:** Spelling & Title Block | **Check key:** `lastausgleich`

## Display Name

Lastausgleichgehänge Note

## Pass

PASS — Lastausgleichgehänge note status matches the lifting anchors in the Einbauteilliste.

## Not Found

NOT FOUND — Einbauteilliste (embedded parts list) not found in the drawing.

## Description

Checks whether the "Lastausgleichgehänge" (load-balancing hanger) note is correctly present or absent, based on how many lifting anchors the Einbauteilliste carries:

- If a lifting-anchor row has Menge (quantity) **≥ 4** → the drawing **must** contain the text "Lastausgleichgehänge". FAIL if missing.
- If the largest lifting-anchor quantity is **< 4** (or the list carries no lifting anchor) → the note **must not** be present. FAIL if found.

**Identifying a lifting anchor.** A lifting anchor is named, not coded — only some carry an RD thread code, so the product wording identifies it:

| Recognised as a lifting anchor | Example |
|---|---|
| Transportanker, Kugelkopf, Ankerkopf, Hebeanker, Lastanker | `Philipp Kugelkopf-Transportanker 7.5, L=300mm mit Gummi-Aussparungskörper D=118mm verzinkt` |
| Transportschlaufe, Seilschlaufe, Transportsystem | `Transportschlaufe 3.0, L=400mm` |
| lifting anchor / loop / insert / socket (English) | `Lifting anchor 2.5t, L=200mm galvanised` |
| an RD thread code written without a space | `Frimeda Transportanker RD24` |

A row naming a lightning-protection product is **not** a lifting anchor even when it carries an RD code — `DEHN RD10 STTZN R81M` is a conductor, not an anchor. Rows mentioning DEHN, Blitzschutz, Erdung, Rundleiter, Potentialausgleich or Fangstange are excluded.

**Reading the quantity.** The Menge is read from the Einbauteilliste's own column order, `<EBT-Nummer> <Menge> <Einheit> <Bezeichnung>`; where the EBT number did not extract, it is read from the quantity printed against its unit (`4 Stk …`). Scanning the row for numbers is not enough — a Bezeichnung is full of them (`7.5`, `L=300mm`, `D=118mm`), and on a wide sheet a schedule row can merge onto the same extracted line.

A line that names an anchor but is **not** a table row is skipped rather than counted. Drawings carry prose that mentions anchors — "Die Lage der Transporthölzer (bei Stützen) ist unterhalb der Transportanker" — and such a line has no Menge to read.

If the Einbauteilliste table is not found in the drawing, the check reports NOT FOUND.
