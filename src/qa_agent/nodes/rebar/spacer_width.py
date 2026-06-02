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
CHECK — Spacer / Clamp Width (spacer_width)
For each spacer or clamp element, verify its width using values from STEP A:
  Required width = wall_width – 2 × Cv + 2 × Ø_spacer   (round up to nearest mm)
  where Ø_spacer = physical diameter of the spacer/clamp wire, read from its label in this drawing.
  [Formula illustration only — values are not from any real drawing]:
    e.g. if wall_width=20, Cv=2.0, Ø_spacer=0.6 → 20 – 4.0 + 1.2 = 17.2 → 18 cm

Flag if the labeled spacer/clamp width clearly differs from the calculated value.
If any required dimension (wall_width, Cv, or Ø_spacer) cannot be found, add "spacer_width" to not_found.\
"""


def spacer_width_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="spacer_width",
        domain="rebar",
        issues_key="rebar_issues",
        check_name="Spacer / Clamp Width",
        pass_desc="PASS — all spacer/clamp widths match wall_width – 2×Cv + 2×Ø_spacer.",
        nf_desc="NOT FOUND — wall thickness, Cv, or spacer wire diameter not visible.",
        prompt=_PROMPT,
    )
