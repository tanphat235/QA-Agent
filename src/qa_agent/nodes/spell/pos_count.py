from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK pos_count — Last Position Number vs Title Block

1. Search the PDF for the labels "letzte Stabstahlposition" and "letzte Mattenposition".

2. For each label found, extract the position number located immediately next to it.
   The number is displayed inside a circle (for Stabstahlposition) or a square (for Mattenposition).
   Use the visually associated number nearest to the label when multiple numbers are present.
   Accept minor OCR variations in the label text.
   → Save as: pos_count_title_stab / pos_count_title_matten (null if label absent or shape empty)

3. Search for the schedule tables "Stabliste" and "Mattenstahlliste".

4. In "Stabliste": collect all Pos numbers. Ignore any Pos ≥ 100 (special accessory bars).
   Find the maximum remaining Pos number.
   → Save as: pos_count_max_stab (null if table absent)

5. In "Mattenstahlliste": collect all Pos numbers. Ignore any Pos ≥ 100.
   Find the maximum remaining Pos number.
   → Save as: pos_count_max_matten (null if table absent)

6. Report all four values in the dedicated output fields. Do NOT add pos_count to the issues list.
   Add "pos_count" to not_found only if BOTH pos_count_title_stab AND pos_count_title_matten are null.\
"""


def pos_count_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="pos_count",
        domain="spell",
        issues_key="spell_issues",
        check_name="Last Position Number vs Title Block",
        pass_desc="PASS — letzte Stabstahlposition and letzte Mattenposition match schedule tables.",
        nf_desc="NOT FOUND — neither 'letzte Stabstahlposition' nor 'letzte Mattenposition' visible in title block.",
        prompt=_PROMPT,
    )
