# Drawing Status
> **Domain:** Spelling & Title Block | **Check key:** `drawing_status`

## Display Name

Drawing Status

## Pass

PASS — Planfreigabe text matches the drawing status code (P → Zur Prüfung; A/F → Zur Ausführung Freigegeben).

## Not Found

NOT FOUND — Status code or Planfreigabe text not found, or status prefix is unrecognised.

## Description

Check that the Planfreigabe approval text is consistent with the first letter of the Status code in the title block:
- Status starts with **P** → Planfreigabe must contain "Zur Prüfung"
- Status starts with **A** or **F** → Planfreigabe must contain "Zur Ausführung Freigegeben"
