# Revision Code Consistency
> **Domain:** Spelling & Title Block | **Check key:** `revision_check`

## Display Name

Revision Code Consistency

## Pass

PASS — Revision code is consistent across the title block, the drawing name and the revision history table.

## Not Found

NOT FOUND — No revision code found in the title block or the drawing name, and no revision history table to compare against.

## Description

Check that the drawing's revision code is stated consistently wherever the sheet carries it.

**Where the revision code is read from, in order:**

1. The title block "Revision" field.
2. The drawing name / Plan-ID, when the sheet has no Revision field. Title block layouts differ per drawing type and many carry no such field; those sheets state the code in the last two dash-separated tokens of their name, revision first and status second — `04-GBC-BW-TPL_-ST-GESAMT-5-FT-050-B-F` gives revision `B` and status `F`. A name whose trailing tokens are not codes yields nothing rather than a guess; two bare letters (`-ST`, `-FT`) are ordinary name segments, not codes.

**Comparisons — whichever the sheet supports:**

| Compared | Reported when |
|---|---|
| Revision code vs. the most recent row (topmost) of the revision history table | they differ |
| Title block "Revision" field vs. the code at the end of the drawing name | they differ, when the sheet carries both |

NOT FOUND is reported only when neither comparison can run.
