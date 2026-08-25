# Steel Content (kg/m³)
> **Domain:** Spelling & Title Block | **Check key:** `steel_content`

## Display Name

Steel Content (kg/m³)

## Pass

PASS — Steel content (Gesamtmasse ÷ Volumen) is within the expected range for the element type.

## Not Found

NOT FOUND — Total steel mass (Gesamtmasse), element volume (Volumen), or the element type in the drawing title not found.

## Description

Extracts the total reinforcement mass (Gesamtmasse [kg]) from all steel schedules (Stabliste, Mattenstahlliste) on the drawing and divides it by the element volume (Volumen [m³]) from the title block to calculate the steel content in kg/m³. The result is then compared against the plausible range for the element type.

Formula: steel content = Σ Gesamtmasse [kg] ÷ Volumen [m³]

The element type is read from the sheet's own wording. Drawings name their element in the title block — "Schalung und Bewehrung FT.- Wandplatte-Achse A-W503.1" (wall), "Formwork and reinforcement Pr.- TT-Plate-202-850" (slab), or a "Bauteil / Component" field — but which of those fields carries the name, and whether it extracts cleanly, varies from one drawing set to the next. A sheet metres wide also flattens into text lines that span the whole page, so the title arrives glued to whatever rebar callouts share its y-band.

The check therefore collects every line that could name the element, ordered with the title-block fields first and incidental mentions last, and the model picks from them. It must quote the wording it read the type from, and answers "unknown" when no line names one. The ratio and the range comparison stay deterministic.

Expected steel content per element type (both bounds inclusive):

| Element type | Range [kg/m³] |
|--------------|---------------|
| Wall         | 50–250        |
| Column       | 80–350        |
| Beam         | 70–300        |
| Slab         | 40–200        |

A result inside the range passes and the PASS message reports the computed value, e.g. "PASS — Steel content: 392.29 kg / 3.21 m³ = 122.1 kg/m³ — within Wall range 50–250 kg/m³".

A result outside the range is reported as an error. When the drawing title names no recognised element type, there is no range to compare against and the check reports NOT FOUND rather than assuming one.
