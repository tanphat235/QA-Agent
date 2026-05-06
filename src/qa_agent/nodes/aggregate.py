from qa_agent.state import GraphState, Issue

_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def aggregate_results(state: GraphState) -> dict:
    all_issues: list[Issue] = [
        *(state.get("spell_issues") or []),
        *(state.get("bend_issues") or []),
        *(state.get("rebar_issues") or []),
    ]

    seen: set[tuple] = set()
    deduped: list[Issue] = []

    for issue in all_issues:
        key = (
            issue.get("category", "unknown"),
            issue.get("page", 1),
            issue.get("description", "").strip().lower()[:80],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)

    deduped.sort(key=lambda i: (
        _SEVERITY_RANK.get(i.get("severity", "info"), 99),  # type: ignore[arg-type]
        i.get("page", 1),
        i.get("category", ""),
    ))

    by_category: dict[str, list[Issue]] = {"spell": [], "bend": [], "rebar": []}
    for issue in deduped:
        cat = issue.get("category", "unknown")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(issue)

    summary = {
        "total":    len(deduped),
        "errors":   sum(1 for i in deduped if i.get("severity") == "error"),
        "warnings": sum(1 for i in deduped if i.get("severity") == "warning"),
        "info":     sum(1 for i in deduped if i.get("severity") == "info"),
        "by_category": {cat: len(items) for cat, items in by_category.items()},
    }

    return {
        "validation_results": {
            "summary": summary,
            "by_category": by_category,
            "issues": deduped,
        }
    }
