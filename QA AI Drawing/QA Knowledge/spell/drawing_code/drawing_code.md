# Drawing code

> **Domain:** spell | **Check key:** `drawing_code`

## Display Name

Drawing code

## Pass

PASS — top-left element code matches the code suffix in Drawing Title.

## Not Found

NOT FOUND — top-left element code or Drawing Title code suffix could not be read.

## Requires Vision

false

## Description

Compare the element code at the top-left of the sheet with the numeric code suffix at the end of the Drawing Title in the title block. Only the code (e.g. 201-851) is compared — not the full drawing name prefix.

## Check Prompt

CHECK — Drawing Code Match (drawing_code)

This check is evaluated deterministically from PRE-EXTRACTED VALUES when possible.
Use these fields only:
  • Element code (top-left label)
  • Element code (Drawing Title suffix)

RULES:
  • Compare ONLY the two element-code fields above — never the full Drawing Title string.
  • Example: Drawing Title "Schalung und Bewehrung FT.- TT-Platte-201-851" → suffix is "201-851".
  • Example: top-left label "201-851" → codes match → PASS (output nothing).
  • Flag an error ONLY when the two parsed codes differ (e.g. top-left "201-850" vs suffix "201-851").
  • Do NOT flag when the suffix appears inside the full title — that is expected.
  • If either parsed code is missing, add "drawing_code" to not_found.
