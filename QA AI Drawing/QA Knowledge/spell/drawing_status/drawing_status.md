# Drawing Status
> **Domain:** Spelling & Title Block | **Check key:** `drawing_status`

## Display Name

Drawing Status

## Pass

PASS — Planfreigabe text matches the drawing status code (P → Zur Prüfung; A/F → Zur Ausführung Freigegeben).

## Not Found

NOT FOUND — No status code found in the title block or in the drawing name.

## Description

Check that the Planfreigabe approval text agrees with the drawing's status code. **That is the only comparison this check makes** — the status code is never played off against any other field.

**Where the status code is read from, in order:**

1. The title block "Status" field.
2. The drawing name / Plan-ID, when the sheet has no Status field. Title block layouts differ per drawing type and many carry no such field; those sheets state the code as the last dash-separated token of their name, after the revision code — `04-GBC-BW-TPL_-ST-GESAMT-5-FT-050-B-F` gives revision `B` and status `F`.

**The comparison:**

| Status code | Planfreigabe must contain | Reported when |
|---|---|---|
| starts with **P** | "Zur Prüfung" | Planfreigabe does not contain it |
| starts with **A** or **F** | "Zur Ausführung Freigegeben" | Planfreigabe does not contain it |

A status code whose first letter is none of P, A or F has no Planfreigabe rule and is not flagged. When the code is found but the sheet carries no Planfreigabe text, the check PASSES and names the source it read the code from — there is nothing to compare against, and that is not a defect in the drawing. NOT FOUND is reported only when no status code can be found at all.
