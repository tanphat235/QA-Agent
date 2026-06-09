# Pos Coverage in Schemas
> **Domain:** Bending & Schedule | **Check key:** `pos_coverage`

## Display Name

Pos Coverage

## Pass

PASS — all Stabliste positions have a corresponding schema.

## Not Found

NOT FOUND — Stabliste not found on sheet.

## Description

Check the Bewehrung sections and their sub-sections and count the created rebar schemas.
Each rebar type in the Stabliste must be represented by at least one schema. At least one scheme is required in the Bewehrung sections or their sub-sections.

Example: in the Stabliste contains positions 1–19 and 100–104, each of these rebar positions must have at least one corresponding schema.

## Check Prompt

CHECK — Pos Coverage in Schemas (pos_coverage)
Every Pos number listed in the Stabliste must have a corresponding rebar schema visible on the sheet.
See the reference images for examples of what a rebar schema looks like.

WHAT IS A REBAR SCHEMA:
  A rebar schema is a drawn bar-shape figure (straight, L-shaped, U-shaped, or multi-bent) with:
    • Dimension lines on each segment of the bar
    • Pos number adjacent to the figure
    • Quantity, diameter, and total length label in the format:
        (n) Pos ø d  L = xxx cm
      e.g. (2) 38 ø 10 L = 195 cm  |  (4) 37 ø 10 L = 92 cm
  All four elements — shape, dimensions, Pos number, and L= label — must be present.
  A bare annotation in a section view without a drawn shape does NOT count as a schema.

WHERE TO LOOK:
  • Margin columns beside every Schnitt section (a-a, b-b, c-c, etc.)
  • Schema panels grouped in the Bewehrung area
  • Any dedicated schema block anywhere on the sheet

PROCEDURE:
  1. List every Pos number from the Stabliste.
  2. For each Pos, search the entire sheet for its rebar schema (drawn shape + dimensions + Pos + L= label).
  3. For every Pos whose schema is NOT found → output a finding that names the missing Pos explicitly.
     Example description: "Pos 7 has no rebar schema on the sheet."
  4. List ALL missing Pos numbers — one finding per missing Pos, or combine into one finding listing all.

PASS only when every Stabliste Pos has a visible schema.
Do NOT flag a Pos if its schema exists but is small or in an unexpected area — only flag if genuinely absent.

NOT FOUND conditions — add "pos_coverage" to not_found (do NOT silently pass) if:
  • The Stabliste is not visible on the sheet (cannot determine which Pos need schemas)
  • The Bewehrung / schema area of the sheet is not legible enough to scan
