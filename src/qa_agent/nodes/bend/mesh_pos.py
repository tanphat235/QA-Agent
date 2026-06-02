from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Review the bar schedule (Stabliste), mesh schedule (Mattenstahlliste), and rebar schemas in this structural drawing.
Report ONLY issues you can directly observe from clearly visible values in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Mesh Reinforcement Pos (mesh_pos)
This check requires BOTH of the following tables to be present on the sheet:
  • Mattenstahlliste (mesh rebar schedule)
  • Matten-Schneideskizze (mesh cut sketch)
If both are present, verify each mesh Pos listed in the Mattenstahlliste appears in at least one view of the Matten-Schneideskizze.
Flag any mesh Pos that is listed in the Mattenstahlliste but has no corresponding entry in the Matten-Schneideskizze.
If either Mattenstahlliste or Matten-Schneideskizze is absent from the sheet, add "mesh_pos" to not_found.\
"""


def mesh_pos_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="mesh_pos",
        domain="bend",
        issues_key="bend_issues",
        check_name="Mesh Reinforcement Pos",
        pass_desc="PASS — all mesh positions appear in section views.",
        nf_desc="NOT FOUND — Mattenstahlliste or Matten-Schneideskizze absent from sheet.",
        prompt=_PROMPT,
    )
