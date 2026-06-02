# Drawing Title vs Title Block
> **Domain:** Spelling & Title Block | **Check key:** `drawing_title`

## Display Name

Drawing Title vs Title Block

## Pass

PASS — sheet heading matches title block Drawing Title field.

## Not Found

NOT FOUND — sheet heading or title block Drawing Title field not visible.

## Description

Check whether the drawing name matches the drawing name in the title block.

## Reference Images

![Drawing Title vs Title Block example 1](./img_001.png)

## Check Prompt

CHECK — Drawing Title vs Title Block (drawing_title)
Locate the drawing title shown prominently at the top of the sheet (the main heading above the
drawing views, often in a large font or header area).
Also find the Drawing Title field inside the title block (Schriftfeld / title block area, usually
in the lower-right corner of the sheet).

MATCHING RULE:
  The title block Drawing Title field may contain a bilingual entry with German and English
  separated by "/" (e.g. "Schalung und Bewehrung ... / Formwork and reinforcement ...").
  In that case, compare ONLY the German part (the text before the "/" separator) against the
  sheet heading. Minor punctuation differences (trailing period, dash spacing) are acceptable.
  Flag only if the semantic content clearly differs — e.g. different element name, wrong axis label.

  If the title block field contains only one language, compare it directly to the sheet heading.

If the sheet heading is not visible, or the title block Drawing Title field is not visible,
add "drawing_title" to not_found.
Do NOT flag if both texts convey the same meaning with only formatting/punctuation differences.
