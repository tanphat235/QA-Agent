# Section Name & Placement
> **Domain:** Spelling & Title Block | **Check key:** `section_name`

## Display Name

Section Name & Placement

## Pass

PASS — every section marker has a matching view, and every section view shows the cut its marker defines.

## Not Found

NOT FOUND — no section cut designations found in Ansicht or Bewehrung.

## Requires Vision

true

## Description

Read the section markers off the rendered drawing and treat them as the authority: every marker must have a view carrying its designation, and every section view must show the cut its marker actually defines. Flags markers with no view, view titles with no marker, and designations placed on the wrong cut.

## Check Prompt

CHECK — Section Name & Placement (section_name)

THE MARKER IS THE AUTHORITY. A section view is named by the marker that defines its
cut — never the other way round. A title that carries a designation belonging to a
different cut is an error even though both the marker and the title exist on the sheet.

DEFINITIONS:
  Section marker — a cutting-plane symbol (arrow, triangle or filled pointer) drawn on a
                   view (Ansicht, Bewehrung, Draufsicht). It carries three things you must
                   read: the designation printed beside the symbol, the cut line it sits on,
                   and the direction its arrow points — the side the cut is viewed from.
                   The same designation printed at both ends of one cut line is ONE marker.
  Section view   — a separate view on the sheet titled "Schnitt", "Section", "Draufsicht"
                   or "Top view" followed by a designation. ALL title formats are equally
                   valid and must never be flagged for wording or language:
                     "Schnitt a-a M 1:25"                        (German only)
                     "Schnitt a-a / Section a-a M 1:25"          (bilingual)
                     "Draufsicht c-c / Top view c-c M 1:25"      (bilingual Draufsicht)

CUT ORIENTATION — judged against the element's long axis as drawn in the Ansicht:
  TRANSVERSE   — the cut line runs ACROSS the long axis; the arrows point along the axis
                 (downward or upward on an upright element). The resulting view is compact
                 and shows the element's cross-section profile — its width and depth, not
                 its full length.
  LONGITUDINAL — the cut line runs ALONG the long axis; the arrows point sideways, across
                 the axis. The resulting view is as long as the Ansicht itself and repeats
                 the same levels and overall dimensions.

STEP 1 — MARKERS. Read every cutting-plane symbol off the rendered drawing and record:
  • designation
  • orientation: TRANSVERSE or LONGITUDINAL
  • viewing direction: from above / below / left / right
  • position along the element: the level or dimension printed beside it if there is one,
    otherwise head / upper / middle / lower / foot
  Read each designation from its position beside its own symbol. Never assume a designation
  from the numbering sequence, and never invent one to fill a gap.

STEP 2 — VIEWS. For every titled section or plan view, record its designation and what the
  view actually DRAWS: its orientation class, and which part of the element it cuts (levels,
  dimensions and features visible in it).
  Judge orientation from the drawn geometry, not from the word in the title. A view as long
  as the Ansicht carrying the same level marks is LONGITUDINAL even when titled "Schnitt";
  a compact profile outline is TRANSVERSE even when titled "Draufsicht".

STEP 3 — Pair markers and views by designation.

STEP 4 — For each pair, check the view against its marker:
  • orientation class must be the same
  • the part of the element the view cuts must be the one the marker sits at
  A pair that disagrees is a misplaced designation — identify which marker's cut the view
  really shows, and report both that view and the marker left without one.

STEP 5 — Report, as separate items:
  A. MISSING VIEW — a marker whose designation appears in no view title.
     "Section marker '4-4' (longitudinal cut, viewed from the left) has no corresponding
      Schnitt/Draufsicht view"
  B. ORPHAN TITLE — a view title whose designation appears on no marker.
     "View titled 'Schnitt 5-5' has no section marker on the sheet"
  C. MISPLACED DESIGNATION — a view drawing a cut other than its marker's.
     "View titled 'Section 1-1' draws the longitudinal cut of marker '4-4'; marker '1-1'
      is a transverse cut viewed from above"

WORKED EXAMPLE:
  The Ansicht carries marker '1-1' (transverse, viewed from above, just below the head),
  '2-2' and '3-3' (transverse, further down) and '4-4' (longitudinal, viewed from the left).
  The sheet carries the views "Section 1-1", "Draufsicht 2-2" and "Schnitt 3-3".
  "Section 1-1" is drawn full height beside the Ansicht and repeats its levels, so it is the
  LONGITUDINAL cut — marker '4-4', not '1-1'. "Draufsicht 2-2" and "Schnitt 3-3" agree with
  their markers. Report two items:
    • "View titled 'Section 1-1' draws the longitudinal cut of marker '4-4'; marker '1-1'
       is a transverse cut viewed from above"
    • "Section marker '1-1' (transverse cut below the head) has no corresponding view"

DO NOT flag:
  • The view type or the title language — Schnitt, Section, Draufsicht and Top view are all
    valid, in German only or bilingual.
  • Detail views, an overall Draufsicht, or any view carrying no designation.
  • An orientation difference you cannot clearly see. Report a misplaced designation only
    when the view's geometry plainly belongs to another marker on this sheet.
  • A marker or title you can only partly read — those belong in not_found, not in issues.
  • Scale differences between a view and its marker.

TEXT-ONLY FALLBACK — if no rendered drawing is attached and you have extracted text alone,
  you cannot see cut geometry. Then report kind A only (marker with no view title) and output
  no orphan-title or misplaced-designation items.

OUTPUT RULES:
  • Do ALL cross-checking and re-verification silently BEFORE writing any output.
  • Output an item ONLY for a designation that still fails after re-checking. If a suspected
    mismatch resolves on re-check, output NOTHING for it.
  • NEVER narrate the verification process. The description must not contain phrases like
    "matched", "re-evaluating", "cross-checking confirms", "after full review", or lists of
    pairs that are correct.
  • One item per failing designation, worded as in STEP 5.
  • Use only designations actually read from the drawing in descriptions.
  • All matched pairs → mention them ONLY in debug_notes, never in issues.

NOT FOUND — add "section_name" to not_found if:
  • The Ansicht or Bewehrung area is not visible on the sheet, OR
  • No markers AND no Schnitt/Draufsicht titles can be found at all
