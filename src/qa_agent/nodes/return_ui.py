from qa_agent.state import GraphState


def return_to_ui(state: GraphState) -> dict:
    results = state.get("validation_results") or {}

    ui_response = {
        "status": "completed",
        "pdf_pages": state.get("page_count") or 0,
        "summary": results.get("summary", {}),
        "by_category": results.get("by_category", {}),
        "issues": results.get("issues", []),
    }

    return {"ui_response": ui_response}
