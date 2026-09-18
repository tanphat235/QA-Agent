# Section Name & Placement
> **Domain:** Spelling & Title Block | **Check key:** `section_name`

## Display Name

Section Name & Placement

## Pass

PASS — every section view carries the designation of the marker whose cut it draws, and no marker is left without a view.

## Not Found

NOT FOUND — no section cut designations found in Ansicht or Bewehrung.

## Requires Vision

true

## Description

Read the section markers off the rendered drawing and treat them as the authority: every section view must carry the designation of the marker whose cut it actually draws.

Views and markers are paired **by position, never by designation** — the designation is the thing under test. Within each orientation class the markers are put in the order their cuts run down the element, the views in the order they are laid out on the sheet, and the n-th marker is matched to the n-th view. Pairing by designation instead would let a whole set of titles shifted by one look correct, and only the one title left without a counterpart would ever be reported.

Each view whose designation is not its marker's is reported on its own, naming the title it should carry. Markers left without a view and views left without a marker are reported too. The type word (Schnitt / Draufsicht / Section / Top view) is not under test here — a wrong language belongs to the spelling check — and appears only inside the corrected title.

## Check Prompt

CHECK — Section Name & Placement (section_name)

THE MARKER IS THE AUTHORITY. A section view is named by the marker that defines its
cut — never the other way round. The designation in a view's title is the thing under
test: it must be the designation of the marker whose cut that view actually draws.

DEFINITIONS:
  Section marker — a cutting-plane symbol (arrow, triangle or filled pointer) drawn on a
                   view (Ansicht, Bewehrung, Draufsicht). It carries three things you must
                   read: the designation printed beside the symbol, the cut line it sits on,
                   and the direction its arrow points — the side the cut is viewed from.
                   The same designation printed at both ends of one cut line is ONE marker.
  Section view   — a separate view on the sheet titled "Schnitt", "Section", "Draufsicht"
                   or "Top view" followed by a designation.

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
  • WHERE ALONG THE ELEMENT it cuts — this is what pairs it with a view, so read it for
    every marker: the level or dimension printed beside it if there is one, otherwise its
    rank down the element (1st from the head, 2nd, 3rd …).
  Read each designation from its position beside its own symbol. Never assume a designation
  from the numbering sequence, and never invent one to fill a gap.

STEP 2 — VIEWS. For every titled section or plan view, record:
  • the designation printed in its title, and the type word it uses
  • what the view actually DRAWS: its orientation class, and which part of the element it
    cuts (levels, dimensions and features visible in it)
  • WHERE IT SITS on the sheet, so the views can be put in layout order.
  Judge orientation from the drawn geometry, not from the word in the title. A view as long
  as the Ansicht carrying the same level marks is LONGITUDINAL even when titled "Schnitt";
  a compact profile outline is TRANSVERSE even when titled "Draufsicht".

STEP 3 — PAIR BY POSITION. NEVER BY DESIGNATION.
  The designation is the thing under test, so it cannot also be what decides which view
  belongs to which marker. On a sheet where every title is one step out of step, pairing
  by designation makes the wrong titles look right and hides the error entirely.

  Pair inside each orientation class:
    • Put the TRANSVERSE markers in the order their cuts run down the element — the one
      nearest the head first, then each one below it.
    • Put the TRANSVERSE views in the order they are laid out on the sheet, reading the way
      the sheet reads: down a column of views, then on to the next column.
    • The 1st marker belongs to the 1st view, the 2nd to the 2nd, and so on.
    • Do the same for the LONGITUDINAL markers and the full-height views.
  When a class has more markers than views, or more views than markers, pair as far as the
  shorter list reaches and report what is left over under A or B.

STEP 4 — THE TITLE MUST CARRY ITS MARKER'S DESIGNATION.
  For each pair, compare the designation in the view's title with the designation on its
  marker. They must be the same.
  The view's TYPE WORD is not under test here — Schnitt, Draufsicht, Section and Top view
  all describe what a view draws, and a wrong language is the spelling check's business.
  Only the designation has to follow the marker.
  When you state the title a view should carry, write the type word that suits what the
  view draws, in the language the rest of the sheet uses.

STEP 5 — Report, as separate items, ONE PER VIEW OR MARKER AT FAULT:
  A. MISSING VIEW — a marker left with no view after pairing.
     "Section marker '4-4' (longitudinal cut, viewed from the left) has no section view"
  B. EXTRA VIEW — a view left with no marker after pairing.
     "View titled 'Schnitt 5-5' has no section marker on the sheet"
  C. MISNAMED VIEW — a view whose designation is not its marker's.
     "View titled 'Draufsich 2-2' draws the 1st transverse cut down the element, which
      marker '1-1' defines — it should be titled 'Draufsicht 1-1'"
  A sheet whose titles are all shifted by one produces ONE item PER VIEW. Report every one
  of them; reporting only the view that happens to have no counterpart hides the defect.

WORKED EXAMPLE — a whole set of titles shifted by one:
  The Ansicht carries four markers. Running down the element: '1-1' (transverse, viewed from
  above, below the head), '2-2' (transverse, middle), '3-3' (transverse, at the foot). Beside
  them sits '4-4' (longitudinal, viewed from the side, cutting the full height).
  The sheet carries four views, in this layout order: "Section 1-1" drawn full height beside
  the Ansicht, then a column of three compact views — "Draufsich 2-2", "Schnitt 3-3",
  "Schnitt 4-4".

  Pair by position, not by number:
    LONGITUDINAL  marker '4-4'  ↔  "Section 1-1"     (the only full-height view)
    TRANSVERSE    marker '1-1'  ↔  "Draufsich 2-2"   (1st cut down ↔ 1st compact view)
                  marker '2-2'  ↔  "Schnitt 3-3"     (2nd ↔ 2nd)
                  marker '3-3'  ↔  "Schnitt 4-4"     (3rd ↔ 3rd)

  Every title is one step out, so report FOUR items:
    • "View titled 'Section 1-1' draws the longitudinal cut that marker '4-4' defines —
       it should be titled 'Schnitt 4-4'"
    • "View titled 'Draufsich 2-2' draws the 1st transverse cut down the element, which
       marker '1-1' defines — it should be titled 'Draufsicht 1-1'"
    • "View titled 'Schnitt 3-3' draws the 2nd transverse cut down the element, which
       marker '2-2' defines — it should be titled 'Schnitt 2-2'"
    • "View titled 'Schnitt 4-4' draws the 3rd transverse cut down the element, which
       marker '3-3' defines — it should be titled 'Schnitt 3-3'"

DO NOT flag:
  • A view whose only fault is its type word or its language. "Section" instead of "Schnitt"
    on a German sheet belongs to the spelling check; name the right type word only inside
    the corrected title you propose here.
  • Detail views, an overall Draufsicht, or any view carrying no designation.
  • A pairing you cannot see. If the markers or the views cannot be put in a definite order
    from the rendered sheet, report only kinds A and B and leave the designations alone.
  • A marker or title you can only partly read — those belong in not_found, not in issues.
  • Scale differences between a view and its marker.

TEXT-ONLY FALLBACK — if no rendered drawing is attached and you have extracted text alone,
  you can see neither cut geometry nor layout order. Then report kind A only (a designation
  on a marker that appears in no view title) and output no other item.

OUTPUT RULES:
  • Do ALL pairing and re-verification silently BEFORE writing any output.
  • Output an item ONLY for a view or marker that still fails after re-checking.
  • NEVER narrate the verification process. The description must not contain phrases like
    "matched", "re-evaluating", "cross-checking confirms", "after full review", or lists of
    pairs that are correct.
  • One item per failing view or marker, worded as in STEP 5, always naming the title the
    view should carry.
  • Use only designations actually read from the drawing in descriptions.
  • All correct pairs → mention them ONLY in debug_notes, never in issues.

NOT FOUND — add "section_name" to not_found if:
  • The Ansicht or Bewehrung area is not visible on the sheet, OR
  • No markers AND no Schnitt/Draufsicht titles can be found at all
