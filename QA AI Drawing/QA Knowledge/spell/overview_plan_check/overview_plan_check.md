# Overview Plan vs Title Block
> **Domain:** Spelling & Title Block | **Check key:** `overview_plan_check`

## Display Name

Overview Plan vs Title Block

## Pass

PASS — Element data in the title block matches what the overview plan states for this element.

## Not Found

NOT FOUND — Overview plan not uploaded, or the element could not be located on it.

## Description

Compares the element data in the drawing title block against what the overview plan states for the same element.

**Step 1 — Element identification, two routes.**

*Preferred — by element code.* Sheets that print their element code in the top-left corner (e.g. `ST-11-01`) are matched on that code, because the overview plan names the same element by it.

The code is read **by position, not by shape**. Element codes have nothing in common across projects — `ST-11-01`, `202-850`, `ST-25-1NT-01`, `W1.2/A` — so nothing here pattern-matches them. The corner label is simply the first standalone short line in the sheet's top-left corner, taken exactly as printed. On the plan side an element is found the same way: a table row is a token with a drawing number immediately to its right, and a callout is a token with its field lines stacked directly underneath. Whatever token sits in either place is the element code.

The plan states the element twice and both are read:

- a **table row** — element code, drawing number, drawing title, Anzahl, Statische Positionsnummer;
- a **callout block** drawn beside the element on the plan itself:

  ```
  ST-11-01
  Stat. Pos. ST-11
  bxh= 50x50cm
  UK-Stütze= -3.25
  Gewicht= 7.79 T
  ```

Overview plans are metres wide and lay several tables side by side, so a flat text extraction puts six unrelated elements on one line and splits each callout into one line per y-band. Both shapes are therefore read from word coordinates — find the code, read to its right for the row and below it for the callout — which does not depend on any one plan's layout. Where the two disagree, the table row wins; the callout only fills fields the row does not carry.

*Fallback — by drawing number.* Sheets with no top-left code, or whose code the plan does not name, fall back to matching the overview plan's statistics table by Drawing No. (primary) or by the element code parsed from the drawing title (secondary).

**Step 2 — Fields compared:**

| Title block field | Overview plan field | Tolerance |
|---|---|---|
| Volumen / Volume (m³) | volume | ±1% |
| Gewicht / Weight (t) | weight | ±1% |
| Anzahl / Quantity | quantity | ±1% |
| Statische Positionsnummer | stat_pos | exact |
| Plan-ID / Drawing No. | drawing_no | exact, ignoring the revision and status codes the sheet appends to its own name (`…-FT-050-B-F` is compared as `…-FT-050`) |

**A field the overview plan does not state is skipped, not failed.** These plans commonly carry no Volumen anywhere; a column the plan simply does not have is not a defect in the drawing. A field the plan states but the drawing does not yield is reported, since that is a value the check was unable to verify.

Any mismatch raises an error. This check is only active when an Overview Plan PDF has been uploaded as a supplementary file.
