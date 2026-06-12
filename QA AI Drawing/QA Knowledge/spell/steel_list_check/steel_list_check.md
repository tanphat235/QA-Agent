# Steel List vs Drawing

> **Domain:** Spelling & Title Block | **Check key:** `steel_list_check`

## Display Name

Steel List vs Drawing

## Pass

PASS — Steel list values match the drawing schedules.

## Not Found

NOT FOUND — Steel list not uploaded or schedules not found in drawing.

## Description

Compares values from the supplementary steel list PDF against the corresponding schedules in the drawing PDF.

**Fields compared:**

| Drawing field | Steel list field | Tolerance |
|---|---|---|
| Stabliste Gesamtmasse [kg] | Stabliste Gesamtmasse [kg] | ±1% |
| Mattenstahlliste Gesamtgewicht [kg] | Mattenstahlliste Gesamtgewicht [kg] | ±1% |
| Einbauteilliste — EBT-Nummer | Einbauteilliste — EBT-Nummer | exact |
| Einbauteilliste — Hersteller | Einbauteilliste — Hersteller | exact |
| Einbauteilliste — Bezeichnung | Einbauteilliste — Bezeichnung | exact |
| Einbauteilliste — Korrosionsschutz | Einbauteilliste — Korrosionsschutz | exact |
| Einbauteilliste — Menge (Stück) | Einbauteilliste — Menge (Stück) | exact |

Any mismatch raises an error. If the steel list PDF has not been uploaded, the check reports NOT FOUND.

This check is only active when a Steel List PDF has been uploaded as a supplementary file.
