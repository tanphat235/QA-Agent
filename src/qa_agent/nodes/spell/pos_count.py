from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Last Position Number vs Title Block (pos_count)
The title block contains two fields that declare the last (highest) position number used:
  • "letzte Stabstahlposition" — last regular bar position in the Stabliste
  • "letzte Mattenposition"    — last mesh position in the Mattenstahlliste (if mesh is present)

PROCEDURE for Stabliste:
  1. Scan the Stabliste and find the highest Pos number that is ≤ 99 (ignore Pos 100+ completely).
  2. Read the value in the "letzte Stabstahlposition" field of the title block.
  3. If highest_pos_≤99 == title_block_value → PASS, do NOT flag anything.
  4. If highest_pos_≤99 ≠ title_block_value → flag as an issue.

PROCEDURE for Mattenstahlliste (only if the table is present on the sheet):
  1. Find the highest Pos number listed in the Mattenstahlliste.
  2. Read the value in the "letzte Mattenposition" field of the title block.
  3. If highest_mesh_pos == title_block_value → PASS, do NOT flag anything.
  4. If highest_mesh_pos ≠ title_block_value → flag as an issue.

IMPORTANT:
  • The presence of Pos 100, 101, 102, … in the Stabliste is normal and expected.
    These are special accessory bars. They do NOT affect letzte Stabstahlposition at all.
    If the title block value equals the highest regular Pos (≤99), the check PASSES — period.
  • Only flag when the numbers clearly and unambiguously differ.

If "letzte Stabstahlposition" is not visible in the title block, add "pos_count" to not_found.
If Mattenstahlliste is absent, skip the mesh part of this check (do NOT add to not_found for that).\
"""


def pos_count_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="pos_count",
        domain="spell",
        issues_key="spell_issues",
        check_name="Last Position Number vs Title Block",
        pass_desc="PASS — letzte Stabstahlposition and letzte Mattenposition match schedule tables.",
        nf_desc="NOT FOUND — 'letzte Stabstahlposition' field not visible in title block.",
        prompt=_PROMPT,
    )
