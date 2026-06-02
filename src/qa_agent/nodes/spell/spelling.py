from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

_PROMPT = _TASK_INTRO + "\n\n" + """\
CHECK — Spelling Errors (spelling)
Flag clear spelling mistakes in German or English words in titles, labels, notes, callouts, or title block.
Do NOT flag: accepted engineering abbreviations (Ø, typ., M.E., Reinf., Bew., pos.), capitalization style.\
"""


def spelling_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="spelling",
        domain="spell",
        issues_key="spell_issues",
        check_name="Spelling Check",
        pass_desc="PASS — no spelling errors found in drawing text.",
        nf_desc="NOT FOUND — no readable text found on sheet.",
        prompt=_PROMPT,
    )
