from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Review the bar schedule (Stabliste), mesh schedule (Mattenstahlliste), and rebar schemas in this structural drawing.
Report ONLY issues you can directly observe from clearly visible values in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Bending Angle / Mandrel Diameter (bending_angle)
For each rebar schema, verify any explicitly labeled mandrel diameter using these minimum values:
  Ø8  → factor 4, min. dbr = 3.2 cm
  Ø10 → factor 4, min. dbr = 4.0 cm
  Ø12 → factor 4, min. dbr = 4.8 cm
  Ø16 → factor 4, min. dbr = 6.4 cm
  Ø20 → factor 7, min. dbr = 14.0 cm
  Ø24 → factor 7, min. dbr = 16.8 cm
  Ø28 → factor 7, min. dbr = 19.6 cm
Flag if a labeled mandrel diameter in the schema is clearly below the minimum for that bar size.
Do NOT flag unlabeled bending radii or diameters.\
"""


def bending_angle_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="bending_angle",
        domain="bend",
        issues_key="bend_issues",
        check_name="Bending Angle / Mandrel Diameter",
        pass_desc="PASS — all labeled mandrel diameters comply with minimum requirements.",
        nf_desc="NOT FOUND — no labeled mandrel diameters found in schemas.",
        prompt=_PROMPT,
    )
