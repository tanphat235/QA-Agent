# Mesh-to-Total Mass Ratio
> **Domain:** Bending & Schedule | **Check key:** `mesh_ratio`

## Display Name

Mesh-to-Total Mass Ratio

## Pass

PASS — mesh reinforcement ratio >= 85 %.

## Not Found

NOT FOUND — Mattenstahlliste or Matten-Schneideskizze absent, or Gesamtmasse totals not visible.

## Description

check that the ratio of used mesh reinforcement to the total reinforcement quantity is greater than 85%.

Ratio = (226.09/231.99)*100 = 97.46% Pass

## Check Prompt

CHECK — Mesh-to-Total Mass Ratio (mesh_ratio)
PREREQUISITE CHECK — do this BEFORE any calculation:
  Confirm that BOTH of the following tables are physically visible on the sheet:
    1. Mattenstahlliste — a table listing mesh reinforcement positions with mass values
       and a "Gesamt" (total) row showing total mesh mass.
    2. Matten-Schneideskizze — a sketch/diagram showing how the mesh sheets are cut,
       usually titled "Matten-Schneideskizze" with rectangular mesh panel outlines and dimensions.

  If EITHER table is absent or not clearly visible → add "mesh_ratio" to not_found and STOP.
  Do NOT calculate the ratio. Do NOT silently pass. Do NOT assume the tables are present.
  (Note: Mattenstahlliste alone is not sufficient — Matten-Schneideskizze must also be present.)

If both tables are confirmed present, also confirm Stabliste is present, then calculate:
  ratio = (total_mesh_mass / (total_rebar_mass + total_mesh_mass)) × 100
Flag if ratio < 85 %.
Obtain totals from the "Gesamt" rows of each schedule.
If the Gesamt totals are not clearly visible, add "mesh_ratio" to not_found.
