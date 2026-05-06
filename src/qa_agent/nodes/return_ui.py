from qa_agent.state import GraphState

_CATEGORY_TITLES = {
    "spell": "Drawing Labels & Annotation",
    "bend":  "Bending & Bar Schedule",
    "rebar": "Rebar Labels & Dimensions",
}

_CATEGORY_ORDER = ["bend", "rebar", "spell"]


def return_to_ui(state: GraphState) -> dict:
    issues: list[dict] = list((state.get("validation_results") or {}).get("issues") or [])

    # Normalize severity to uppercase in-place
    for issue in issues:
        issue["severity"] = str(issue.get("severity", "info")).upper()

    error_count   = sum(1 for i in issues if i.get("severity") == "ERROR")
    warning_count = sum(1 for i in issues if i.get("severity") == "WARNING")
    info_count    = sum(1 for i in issues if i.get("severity") == "INFO")
    total_count   = len(issues)

    # Group by category and assign sequential IDs
    by_category: dict[str, list] = {cat: [] for cat in _CATEGORY_ORDER}
    counters: dict[str, int] = {}
    for issue in issues:
        cat = str(issue.get("category", "unknown")).lower()
        if cat not in by_category:
            by_category[cat] = []
        counters[cat] = counters.get(cat, 0) + 1
        by_category[cat].append({**issue, "id": f"{cat.upper()}-{counters[cat]:03d}"})

    sections = [
        {
            "category": cat,
            "title": _CATEGORY_TITLES.get(cat, cat.title()),
            "count": len(by_category[cat]),
            "issues": by_category[cat],
        }
        for cat in _CATEGORY_ORDER
    ]

    status  = "passed" if total_count == 0 else "completed"
    message = (
        "No QA issues found. Drawing is clean."
        if total_count == 0
        else (
            f"Analysis completed. Found {total_count} issue(s): "
            f"{error_count} error, {warning_count} warning, {info_count} info."
        )
    )

    return {
        "ui_response": {
            "status":    status,
            "message":   message,
            "pdf_pages": state.get("page_count") or 0,
            "summary": {
                "total":   total_count,
                "ERROR":   error_count,
                "WARNING": warning_count,
                "INFO":    info_count,
            },
            "sections": sections,
        }
    }
