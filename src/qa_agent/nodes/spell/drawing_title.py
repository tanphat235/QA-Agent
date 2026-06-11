from qa_agent.state import GraphState
from qa_agent.nodes._base import run_check
from qa_agent.rag.retriever import get_check_prompt

# Prompt is the single source of truth from the .md knowledge file.
_PROMPT = get_check_prompt("spell", "drawing_title")


def drawing_title_check(state: GraphState) -> dict:
    return run_check(
        state,
        check_key="drawing_title",
        domain="spell",
        issues_key="spell_issues",
        check_name="Drawing Title vs Title Block",
        pass_desc="PASS — Drawing Title and Drawing No. are present and titles are consistent.",
        nf_desc="NOT FOUND — Drawing Title or Drawing No. field is absent or empty in the title block.",
        prompt=_PROMPT,
    )
