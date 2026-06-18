from qa_agent.state import GraphState

_CATEGORY_TITLES = {
    "spell":  "Spelling & Title Block",
    "bend":   "Bending & Schedule",
    "rebar":  "Rebar Labels & Dims",
}

_CATEGORY_ORDER = ["bend", "rebar", "spell"]


def _is_check_summary(issue: dict) -> bool:
    """True for per-check PASS/FAIL/NOT FOUND summary items (not individual findings)."""
    if "passed" in issue or issue.get("not_found") is True:
        return True
    desc = str(issue.get("description", ""))
    return desc.startswith(("✓", "PASS", "N/A", "NOT FOUND"))


def _build_message(error_count: int, warning_count: int, info_count: int,
                   real_total: int, summary_count: int, not_found_count: int) -> tuple[str, str]:
    """Return (status, message) based on issue counts."""
    if error_count > 0 or warning_count > 0:
        nf_note = f", {not_found_count} not found" if not_found_count > 0 else ""
        return "completed", (
            f"Analysis completed. Found {real_total} issue(s): "
            f"{error_count} error, {warning_count} warning, {info_count} info{nf_note}."
        )
    if real_total == 0 and not_found_count > 0:
        return "passed", (
            f"QA checks completed. No errors or warnings found. "
            f"{not_found_count} check(s) could not be verified — required drawing info absent."
        )
    if real_total == 0 and summary_count > 0:
        return "passed", (
            f"QA checks completed. No errors or warnings found. "
            f"{summary_count} check area(s) verified clean."
        )
    if real_total == 0:
        return "passed", "No QA issues found. Drawing is clean."
    return "passed", (
        f"QA checks completed. No errors or warnings. "
        f"{info_count} minor info item(s) noted."
    )


def _build_section(cat: str, items: list) -> dict:
    return {
        "category":          cat,
        "title":             _CATEGORY_TITLES.get(cat, cat.title()),
        "count":             len(items),
        "issue_count":       sum(1 for i in items if not _is_check_summary(i)),
        "checks_passed":     sum(1 for i in items if i.get("passed") is True),
        "checks_failed":     sum(1 for i in items if i.get("passed") is False),
        "checks_not_found":  sum(1 for i in items if i.get("not_found") is True),
        "issues":            items,
    }


def return_to_ui(state: GraphState) -> dict:
    issues: list[dict] = list((state.get("validation_results") or {}).get("issues") or [])

    for issue in issues:
        issue["severity"] = str(issue.get("severity", "info")).upper()

    real_issues   = [i for i in issues if not _is_check_summary(i)]
    summary_items = [i for i in issues if _is_check_summary(i)]

    error_count   = sum(1 for i in real_issues if i.get("severity") == "ERROR")
    warning_count = sum(1 for i in real_issues if i.get("severity") == "WARNING")
    info_count    = sum(1 for i in real_issues if i.get("severity") == "INFO")
    real_total    = len(real_issues)
    summary_count = len(summary_items)

    # Group items by category preserving original order (summary must stay adjacent to its
    # individual findings so the frontend buildCheckGroups can link them correctly).
    by_category: dict[str, list] = {cat: [] for cat in _CATEGORY_ORDER}
    counters: dict[str, int] = {}
    for issue in issues:
        cat = str(issue.get("category", "unknown")).lower()
        if cat not in by_category:
            by_category[cat] = []
        counters[cat] = counters.get(cat, 0) + 1
        by_category[cat].append({**issue, "id": f"{cat.upper()}-{counters[cat]:03d}"})

    not_found_count = sum(1 for i in summary_items if i.get("not_found") is True)
    status, message = _build_message(
        error_count, warning_count, info_count, real_total, summary_count, not_found_count
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
            "sections": [_build_section(cat, by_category[cat]) for cat in _CATEGORY_ORDER],
        }
    }
