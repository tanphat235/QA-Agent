# Scale Consistency
> **Domain:** Spelling & Title Block | **Check key:** `section_scale`

## Display Name

Scale Consistency

## Pass

PASS — all view scales consistent with title block.

## Not Found

NOT FOUND — no scale labels (M 1:XX) visible on views or title block.

## Description

Check whether the drawing scales match the title block.
If any scale in the drawing (section, detail…) differs from the title block, report it as FAIL and update the title block accordingly.

## Reference Images

![Scale Consistency example 1](./img_001.png)

## Check Prompt

CHECK — Scale Consistency (section_scale)
Read all scale values directly from the submitted PDF drawing. All scale values and view names
in these instructions are examples only — do NOT use them as actual values.

Compare every explicit scale label (M 1:XX) on views or sections against the title block scale field.
Flag any view whose labeled scale clearly differs from the title block value.
Only flag where both scales are simultaneously visible and unambiguously different in their numeric ratio.

CRITICAL — scale separator rendering:
  German engineering drawings ALWAYS use colons in scale notation: "1:25", "1:200", "1:50".
  In PDF rendering, the colon ":" is frequently misread as a period ".".
  If you read "1.25" or "1.200", treat it as "1:25" and "1:200" — rendering artifact, NOT an error.
  NEVER flag solely because the separator appears as a period. Only flag when the NUMBERS differ
  (e.g. one view says 1:25, title block says 1:50).

NOT FOUND conditions — add "section_scale" to not_found (do NOT silently pass) if ANY of:
  • The title block is not visible on the sheet
  • The title block scale field is not visible or not readable
  • No scale labels (M 1:XX) appear on any view or section on the sheet
