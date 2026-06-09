# Mesh Reinforcement Pos
> **Domain:** Bending & Schedule | **Check key:** `mesh_pos`

## Display Name

Mesh Reinforcement Pos

## Pass

PASS — all mesh positions appear in Matten-Schneideskizze.

## Not Found

NOT FOUND — Mattenstahlliste or Matten-Schneideskizze absent from sheet.

## Description

check the rebar position of the mesh reinforcement in the drawing, if available.

## Check Prompt

CHECK — Mesh Reinforcement Pos (mesh_pos)
This check requires BOTH of the following tables to be present on the sheet:
  • Mattenstahlliste (mesh rebar schedule)
  • Matten-Schneideskizze (mesh cut sketch)
If both are present, verify each mesh Pos listed in the Mattenstahlliste appears in at least one view of the Matten-Schneideskizze.
Flag any mesh Pos that is listed in the Mattenstahlliste but has no corresponding entry in the Matten-Schneideskizze.
If either Mattenstahlliste or Matten-Schneideskizze is absent from the sheet, add "mesh_pos" to not_found — do NOT silently pass.
