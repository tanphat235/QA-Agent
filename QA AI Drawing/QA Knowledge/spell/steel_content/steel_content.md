# Steel Content (kg/m³)
> **Domain:** Spelling & Title Block | **Check key:** `steel_content`

## Display Name

Steel Content (kg/m³)

## Pass

PASS — Steel content: computed from Gesamtmasse ÷ Volumen (kg/m³).

## Not Found

NOT FOUND — Total steel mass (Gesamtmasse) or element volume (Volumen) not found in the drawing.

## Description

Extracts the total reinforcement mass (Gesamtmasse [kg]) from all steel schedules (Stabliste, Mattenstahlliste) on the drawing and divides it by the element volume (Volumen [m³]) from the title block to calculate the steel content in kg/m³.

Formula: steel content = Σ Gesamtmasse [kg] ÷ Volumen [m³]

The PASS message includes the calculated result (e.g., "PASS — Steel content: 392.29 kg / 3.21 m³ = 122.1 kg/m³").
This is the only check that includes the computed value in the pass message.
