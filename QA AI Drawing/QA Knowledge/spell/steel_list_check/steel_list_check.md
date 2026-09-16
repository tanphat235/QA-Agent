# Steel List vs Drawing

> **Domain:** Spelling & Title Block | **Check key:** `steel_list_check`

## Display Name

Steel List vs Drawing

## Pass

PASS — Steel list schedules match the drawing position by position.

## Not Found

NOT FOUND — Steel list not uploaded or schedules not found in drawing.

## Description

Compares the supplementary steel list PDF against the corresponding schedules in the drawing PDF. Both rebar schedules are compared **row by row**: every position in the Stabliste and the Mattenstahlliste must exist on both documents and carry identical values in every column. Only the schedule totals are allowed a small tolerance.

**Per-position comparison — Stabliste and Mattenstahlliste, identical rules:**

| Column | Tolerance |
|---|---|
| Pos. / Position | exact — must exist on both sides with the same number |
| Stck / Stück | exact |
| Ø [mm] (bar diameter, or mesh type on a mesh row) | exact |
| Einzellänge [m] | exact |
| Gesamtlänge [m] | exact |
| Masse / Gewicht [kg] | exact |

Numbers compare as numbers, so a decimal comma or a trailing zero (`3,50` against `3.5`) is formatting and not a difference. Everything else compares as printed.

**Totals and parts list:**

| Drawing field | Steel list field | Tolerance |
|---|---|---|
| Stabliste Gesamtmasse [kg] | Stabliste Gesamtmasse [kg] | ±1% |
| Mattenstahlliste Gesamtgewicht [kg] | Mattenstahlliste Gesamtgewicht [kg] | ±1% |
| Einbauteilliste — EBT-Nummer | Einbauteilliste — EBT-Nummer | exact |
| Einbauteilliste — Hersteller | Einbauteilliste — Hersteller | exact |
| Einbauteilliste — Bezeichnung | Einbauteilliste — Bezeichnung | exact |
| Einbauteilliste — Korrosionsschutz | Einbauteilliste — Korrosionsschutz | exact |
| Einbauteilliste — Menge (Stück) | Einbauteilliste — Menge (Stück) | exact |

**Reported defects:**

- **Renumbered position** — the same bar (same count, diameter, lengths and mass) carries a different Pos number on each document. Reported as one finding naming both numbers, not as a missing plus an extra row.
- **Missing position** — a position in the drawing schedule that the steel list does not carry.
- **Extra position** — a position in the steel list that the drawing schedule does not carry.
- **Value mismatch** — a position present on both sides whose Stück, Ø, Einzellänge, Gesamtlänge or Masse differs. The finding names every column that differs and both values.
- **Duplicate position** — the same Pos number printed twice in one schedule.
- **Total mismatch** — Gesamtmasse or Gesamtgewicht differing by more than 1%.

Any mismatch raises an error. The check reports NOT FOUND only when nothing at all could be compared — when the steel list has not been uploaded, or when neither document yields a schedule or a parts table. A schedule the drawing does not carry (a wall with no mesh, for instance) is not a defect and does not suppress the comparisons that did run.

This check is only active when a Steel List PDF has been uploaded as a supplementary file.
