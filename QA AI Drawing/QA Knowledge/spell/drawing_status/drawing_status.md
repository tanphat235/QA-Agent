# Drawing Status
> **Domain:** Spelling & Title Block | **Check key:** `drawing_status`

## Display Name

Drawing Status

## Pass

PASS — Status code is consistent with the Planfreigabe text and with the drawing name.

## Not Found

NOT FOUND — No status code found in the title block or the drawing name, and nothing to compare it against.

## Description

Check that the drawing's status code is stated consistently wherever the sheet carries it.

**Where the status code is read from, in order:**

1. The title block "Status" field.
2. The drawing name / Plan-ID, when the sheet has no Status field. Title block layouts differ per drawing type and many carry no such field; those sheets state the code as the last dash-separated token of their name, after the revision code — `04-GBC-BW-TPL_-ST-GESAMT-5-FT-050-B-F` gives revision `B` and status `F`.

**Comparisons — whichever the sheet supports:**

| Compared | Reported when |
|---|---|
| Status code vs. the Planfreigabe approval text | Status starts with **P** and Planfreigabe does not contain "Zur Prüfung", or Status starts with **A** / **F** and Planfreigabe does not contain "Zur Ausführung Freigegeben" |
| Title block "Status" field vs. the code at the end of the drawing name | they differ, when the sheet carries both |

A status code whose first letter is none of P, A or F has no Planfreigabe rule and is not flagged. NOT FOUND is reported only when neither comparison can run.
