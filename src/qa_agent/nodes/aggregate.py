from qa_agent.state import GraphState, Issue

_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def _deduplicate(issues: list[Issue]) -> list[Issue]:
    seen: set[tuple] = set()
    unique: list[Issue] = []
    for issue in issues:
        key = (issue["category"], issue["description"][:80], issue["page"])
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def aggregate_results(state: GraphState) -> dict:
    all_issues: list[Issue] = (
        (state.get("spell_issues") or [])
        + (state.get("bend_issues") or [])
        + (state.get("rebar_issues") or [])
    )

    deduped = _deduplicate(all_issues)
    deduped.sort(key=lambda x: (_SEVERITY_RANK.get(x["severity"], 3), x["page"]))

    by_category = {
        "spell": [i for i in deduped if i["category"] == "spell"],
        "bend": [i for i in deduped if i["category"] == "bend"],
        "rebar": [i for i in deduped if i["category"] == "rebar"],
    }

    summary = {
        "total": len(deduped),
        "errors": sum(1 for i in deduped if i["severity"] == "error"),
        "warnings": sum(1 for i in deduped if i["severity"] == "warning"),
        "info": sum(1 for i in deduped if i["severity"] == "info"),
        "by_category": {k: len(v) for k, v in by_category.items()},
    }

    return {
        "validation_results": {
            "issues": deduped,
            "by_category": by_category,
            "summary": summary,
        }
    }
