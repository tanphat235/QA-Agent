from qa_agent.state import GraphState

_CATEGORY_TITLES = {
    "spell": "Spelling & Title Block",
    "bend":  "Bending & Schedule",
    "rebar": "Rebar Labels & Dims",
}

_CATEGORY_ORDER = ["bend", "rebar", "spell"]


def _is_check_summary(issue: dict) -> bool:
    """True for per-check PASS/FAIL/N/A summary items (not individual findings)."""
    if "passed" in issue:
        return True
    desc = str(issue.get("description", ""))
    return desc.startswith("✓") or desc.startswith("PASS") or desc.startswith("N/A")


def return_to_ui(state: GraphState) -> dict:
    issues: list[dict] = list((state.get("validation_results") or {}).get("issues") or [])

    # Normalize severity to uppercase in-place
    for issue in issues:
        issue["severity"] = str(issue.get("severity", "info")).upper()

    # Separate real findings from per-check PASS/FAIL summaries
    real_issues     = [i for i in issues if not _is_check_summary(i)]
    summary_items   = [i for i in issues if _is_check_summary(i)]

    error_count   = sum(1 for i in real_issues if i.get("severity") == "ERROR")
    warning_count = sum(1 for i in real_issues if i.get("severity") == "WARNING")
    info_count    = sum(1 for i in real_issues if i.get("severity") == "INFO")
    real_total    = len(real_issues)
    summary_count = len(summary_items)

    # Group ALL items by category and assign sequential IDs (real first, then summaries)
    by_category: dict[str, list] = {cat: [] for cat in _CATEGORY_ORDER}
    counters: dict[str, int] = {}
    for issue in real_issues + summary_items:
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
            "issue_count": sum(1 for i in by_category[cat] if not _is_check_summary(i)),
            "checks_passed": sum(1 for i in by_category[cat] if i.get("passed") is True),
            "checks_failed": sum(1 for i in by_category[cat] if i.get("passed") is False),
            "issues": by_category[cat],
        }
        for cat in _CATEGORY_ORDER
    ]

    if error_count == 0 and warning_count == 0:
        status = "passed"
        if real_total == 0 and summary_count > 0:
            message = (
                f"QA checks completed. No errors or warnings found. "
                f"{summary_count} check area(s) verified clean."
            )
        elif real_total == 0:
            message = "No QA issues found. Drawing is clean."
        else:
            message = (
                f"QA checks completed. No errors or warnings. "
                f"{info_count} minor info item(s) noted."
            )
    else:
        status = "completed"
        message = (
            f"Analysis completed. Found {real_total} issue(s): "
            f"{error_count} error, {warning_count} warning, {info_count} info."
        )

    return {
        "ui_response": {
            "status":    status,
            "message":   message,
            "pdf_pages": state.get("page_count") or 0,
            "summary": {
                "total":   real_total,
                "ERROR":   error_count,
                "WARNING": warning_count,
                "INFO":    info_count,
            },
            "sections": sections,
        }
    }
