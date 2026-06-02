from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Review the bar schedule (Stabliste), mesh schedule (Mattenstahlliste), and rebar schemas in this structural drawing.
Report ONLY issues you can directly observe from clearly visible values in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Mesh-to-Total Mass Ratio (mesh_ratio)
This check requires BOTH Stabliste and Mattenstahlliste to be present on the sheet.
If both are present, calculate:
  ratio = (total_mesh_mass / (total_rebar_mass + total_mesh_mass)) × 100
Flag if ratio < 85 %.
Obtain totals from the "Gesamt" (total) rows of each schedule.
If either Stabliste or Mattenstahlliste is absent, or if the Gesamt totals are not clearly visible, add "mesh_ratio" to not_found.\
"""


def mesh_ratio_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="mesh_ratio",
        domain="bend",
        issues_key="bend_issues",
        check_name="Mesh-to-Total Mass Ratio",
        pass_desc="PASS — mesh reinforcement ratio >= 85 %.",
        nf_desc="NOT FOUND — Mattenstahlliste absent or Gesamtmasse totals not visible.",
        prompt=_PROMPT,
    )
