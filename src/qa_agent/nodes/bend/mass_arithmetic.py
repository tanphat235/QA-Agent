from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Review the bar schedule (Stabliste), mesh schedule (Mattenstahlliste), and rebar schemas in this structural drawing.
Report ONLY issues you can directly observe from clearly visible values in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Total Mass Arithmetic (mass_arithmetic)
Verify that the Gesamtmasse (grand total mass) at the bottom of the Stabliste equals the sum
of all individual row Masse [kg] values.

PROCEDURE:
  1. Read every row's Masse [kg] value from the Stabliste.
  2. Sum them: computed_total = Σ Masse_i
  3. Read the Gesamtmasse [kg] footer value.
  4. If computed_total ≠ Gesamtmasse → flag immediately. Any difference is an error.

If the Mattenstahlliste is also present, apply the same check to it independently.

Do NOT flag if individual row values or the Gesamtmasse footer are not clearly readable.
If the Gesamtmasse footer is absent or illegible, add "mass_arithmetic" to not_found.\
"""


def mass_arithmetic_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="mass_arithmetic",
        domain="bend",
        issues_key="bend_issues",
        check_name="Total Mass Arithmetic",
        pass_desc="PASS — sum of row masses matches Gesamtmasse footer.",
        nf_desc="NOT FOUND — Gesamtmasse footer absent or illegible.",
        prompt=_PROMPT,
    )
