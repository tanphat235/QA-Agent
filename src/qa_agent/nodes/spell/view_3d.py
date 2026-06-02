from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — 3D View Present (3d_view)
Check whether the sheet contains a 3D pictorial view of the wall element.

WHAT COUNTS AS A 3D VIEW — ANY ONE of the following is sufficient to pass:

  LABELED VIEWS (pass regardless of visual appearance):
  • Any area or view titled "3D Perspektive", "Perspektive", "isometrische Ansicht",
    "3D Ansicht", "3D View", or any text containing "3D" or "Perspektiv".

  UNLABELED VIEWS (visual recognition — no label required):
  • A drawing of the wall body shown from a diagonal/oblique angle (approximately 45°),
    where the wall appears as a solid rectangular block or slab tilted toward the viewer.
  • Telltale signs: the main face of the wall AND at least one side edge or top edge are
    visible simultaneously; the wall outline lines run diagonally (not purely horizontal
    or vertical); the view gives an overall "bird's eye" or "overview" impression of the
    entire wall element in three dimensions.
  • This type of view is a standard engineering axonometric or isometric line drawing.
    It is typically placed in a corner of the sheet, often without any scale label or title.
    It may show embedded hardware, rebar protruding from the wall face, lifting anchors, etc.
  • Shading, color, or fill are NOT required — a pure line drawing counts.
  • The view may be small or appear in a corner of the sheet — size does not matter.

HOW TO SCAN:
  Look at ALL areas of the sheet, including corners and margins. If you see a rectangular
  wall-shaped outline drawn at a diagonal angle (showing depth), that IS the 3D view.

If ANY such view exists anywhere on the sheet → PASS immediately, do NOT flag.
If after scanning the entire sheet no such view exists → flag as an error.

Do NOT perform any consistency or orientation check — presence alone is sufficient.\
"""


def view_3d_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="3d_view",
        domain="spell",
        issues_key="spell_issues",
        check_name="3D View Present and Consistent",
        pass_desc="PASS — 3D view present and consistent with Ansicht.",
        nf_desc="NOT FOUND — no 3D pictorial (oblique/isometric) view found on sheet.",
        prompt=_PROMPT,
    )
