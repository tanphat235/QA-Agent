from langgraph.graph import StateGraph, START, END

from qa_agent.state import GraphState
from qa_agent.nodes.preprocess import preprocess
from qa_agent.nodes.spell_check import spell_check
from qa_agent.nodes.bend_check import bend_check
from qa_agent.nodes.rebar_check import rebar_check
from qa_agent.nodes.aggregate import aggregate_results
from qa_agent.nodes.return_ui import return_to_ui

_ALL_CHECKS = ["spell", "bend", "rebar"]


def _make_check_node(check_key: str, fn):
    """Wrap a check node so it returns an empty issues list when not enabled."""
    issues_key = f"{check_key}_issues"

    def node(state: GraphState) -> dict:
        enabled = state.get("enabled_checks") or _ALL_CHECKS
        if check_key not in enabled:
            return {issues_key: []}
        return fn(state)

    node.__name__ = fn.__name__
    return node


def build_graph():
    g = StateGraph(GraphState)

    g.add_node("preprocess",        preprocess)
    g.add_node("spell_check",       _make_check_node("spell", spell_check))
    g.add_node("bend_check",        _make_check_node("bend",  bend_check))
    g.add_node("rebar_check",       _make_check_node("rebar", rebar_check))
    g.add_node("aggregate_results", aggregate_results)
    g.add_node("return_to_ui",      return_to_ui)

    g.add_edge(START, "preprocess")

    # Fan out: all check nodes run in parallel
    g.add_edge("preprocess", "spell_check")
    g.add_edge("preprocess", "bend_check")
    g.add_edge("preprocess", "rebar_check")

    # Fan in: aggregate waits for all check nodes to complete
    g.add_edge("spell_check",  "aggregate_results")
    g.add_edge("bend_check",   "aggregate_results")
    g.add_edge("rebar_check",  "aggregate_results")

    g.add_edge("aggregate_results", "return_to_ui")
    g.add_edge("return_to_ui", END)

    return g.compile()


# Module-level export required by LangGraph Studio
graph = build_graph()
