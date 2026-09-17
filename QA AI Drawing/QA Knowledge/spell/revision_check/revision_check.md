# Revision Code Consistency
> **Domain:** Spelling & Title Block | **Check key:** `revision_check`

## Display Name

Revision Code Consistency

## Pass

PASS — Revision code is consistent across the title block, the drawing name and the revision history table.

## Not Found

NOT FOUND — No revision code found in the title block or in the drawing name.

## Description

Check that the drawing's revision code is stated consistently wherever the sheet carries it.

**Where the revision code is read from, in order:**

1. The title block "Revision" field.
2. The drawing name / Plan-ID, when the sheet has no Revision field. Title block layouts differ per drawing type and many carry no such field; those sheets state the code in the last two dash-separated tokens of their name, revision first and status second — `04-GBC-BW-TPL_-ST-GESAMT-5-FT-050-B-F` gives revision `B` and status `F`. A name whose trailing tokens are not codes yields nothing rather than a guess; two bare letters (`-ST`, `-FT`) are ordinary name segments, not codes.

**Which row of the history table is "most recent".** The table is headed `Rev. | Date | Details | By | App` on English sheets and `Nr. | Art der Änderung | Datum | Name | Verteiler` on German ones, and the newest entry sits at the **top** on some drawings and at the **bottom** on others. The newest row is therefore the one with the largest **Datum**, not the one at a fixed end of the table. Only the Datum column counts — a description cell routinely carries dates of its own ("Freigabe Prüfingenieur 04.08.2026 und Architekten Freigabe vom 26.06.2026"). Where no Datum can be read, the highest revision code wins, since revisions ascend.

**Comparisons — whichever the sheet supports:**

| Compared | Reported when |
|---|---|
| Revision code vs. the newest row of the revision history table | they differ |
| Title block "Revision" field vs. the code at the end of the drawing name | they differ, when the sheet carries both |

When the sheet states its revision in only one place and nothing contradicts it, the check PASSES and names the source it read. NOT FOUND is reported only when no revision code can be found at all.
