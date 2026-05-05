from langgraph.graph import StateGraph, START, END

from qa_agent.state import GraphState
from qa_agent.nodes.preprocess import preprocess
from qa_agent.nodes.spell_check import spell_check
from qa_agent.nodes.bend_check import bend_check
from qa_agent.nodes.rebar_check import rebar_check
from qa_agent.nodes.aggregate import aggregate_results
from qa_agent.nodes.return_ui import return_to_ui


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("preprocess", preprocess)
    graph.add_node("spell_check", spell_check)
    graph.add_node("bend_check", bend_check)
    graph.add_node("rebar_check", rebar_check)
    graph.add_node("aggregate_results", aggregate_results)
    graph.add_node("return_to_ui", return_to_ui)

    graph.add_edge(START, "preprocess")

    # Fan out: run all three validators in parallel after preprocessing
    graph.add_edge("preprocess", "spell_check")
    graph.add_edge("preprocess", "bend_check")
    graph.add_edge("preprocess", "rebar_check")

    # Fan in: aggregate waits for all three to complete
    graph.add_edge("spell_check", "aggregate_results")
    graph.add_edge("bend_check", "aggregate_results")
    graph.add_edge("rebar_check", "aggregate_results")

    graph.add_edge("aggregate_results", "return_to_ui")
    graph.add_edge("return_to_ui", END)

    return graph.compile()
