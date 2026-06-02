from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect reinforcement elements, spacers, pin bars, and clamps in this precast wall structural drawing.
Report ONLY issues you can directly observe from visible annotations and dimensions in the PDF.\
"""

_STEP_A = """\
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP A — EXTRACT ACTUAL VALUES FROM THIS DRAWING FIRST
(Complete this step before doing any calculation. Never substitute example numbers.)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A1. wall_width — total wall thickness in cm:
  Read from the FORMWORK cross-section views (Draufsicht X-X, Schnitt X-X in the Ansicht /
  formwork area, NOT the Bewehrung area). A dimension line spanning the full thickness gives
  the value. It may also appear in the title block.
  → Record as: wall_width = [value you read from this drawing] cm

A2. Cv — design concrete cover in cm:
  Read from the title block "BETONDECKUNG" table, column labeled "Cv" (or "Cᵥ"), in mm.
  Divide by 10 to convert to cm. Do NOT use Cmin,dur or ΔCdev.
  → Record as: Cv = [value from BETONDECKUNG table] cm

A3. Ø_layer1 — outermost rebar layer diameter (needed for Horizontal Pin Width check):
  In the SIDE section view (Schnitt a-a in the Bewehrung), find the first rebar layer from
  the wall face inward. Read its label (e.g. "ø 12/15" → Ø12 → 1.2 cm).
  → Record as: Ø_layer1 = [value from this drawing] cm

If any of these values cannot be found in the drawing, do NOT guess or use any number from
the examples below — instead set not_found = true.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\
"""

_PROMPT = _TASK_INTRO + "\n\n" + _STEP_A + "\n\n" + """\
CHECK — Horizontal Pin Width (pin_width_horizontal)
IDENTIFICATION — locate horizontal pins using their bending schema:
  Horizontal pins are schematized in the BOTTOM / HORIZONTAL cross-section view of the Bewehrung
  (e.g. Schnitt b-b). In that view, the pin schema appears as a flat rectangular stirrup whose
  long dimension runs horizontally (wide and shallow). The width dimension labeled on that schema
  is the value to verify.

WIDTH FORMULA (use values from STEP A, not the illustration numbers):
  Required width = wall_width – 2 × Cv – 2 × Ø_layer1   (round down to nearest mm)
  [Formula illustration only — values are not from any real drawing]:
    e.g. if wall_width were 20 cm, Cv=2.0 cm, Ø_layer1=1.0 cm → 20 – 4.0 – 2.0 = 14 cm

Flag if the labeled horizontal pin width clearly differs from the calculated value.
If any required dimension (wall_width, Cv, Ø_layer1, or pin width) cannot be found, add "pin_width_horizontal" to not_found.\
"""


def pin_width_horizontal_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="pin_width_horizontal",
        domain="rebar",
        issues_key="rebar_issues",
        check_name="Horizontal Pin Width",
        pass_desc="PASS — all horizontal pin widths match wall_width – 2×Cv – 2×Ø_layer1.",
        nf_desc="NOT FOUND — wall thickness, Cv, outer rebar diameter, or labeled pin dimension not visible.",
        prompt=_PROMPT,
    )
