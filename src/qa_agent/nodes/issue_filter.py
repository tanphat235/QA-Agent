"""Shared filtering and result assembly for LLM-based QA checks.

Check outcome (PASS / FAIL / NOT FOUND) is derived only from the final filtered
violation list — never from reasoning text inside LLM descriptions.
"""
from __future__ import annotations

import re
from typing import Protocol

from qa_agent.state import Issue

# Drop LLM items that describe a passing / self-resolved result instead of a violation.
_PASS_ITEM_RE = re.compile(
    r"[-–—]\s*pass(?:es)?\b"
    r"|^pass(?:es)?\b"
    r"|\bthis pass(?:es)?\b"
    r"|\bno\s+(?:issues?|errors?|violations?|problems?|findings?|spelling\s+errors?)\s+(?:were\s+)?found\b"
    r"|\bno\s+error\b"
    r"|\bno issue\b"
    r"|\bexactly meets\b"
    r"|\bdeclared\b.{0,30}\bmatches\b.{0,30}\bcalculated\b"
    r"|\bmatches?\b.{0,30}\brequired\b"
    r"|\bvalues?\s+matches?\b"
    r"|\bno unmatched\b"
    r"|\bre-?evaluat"
    r"|\bre-?check(?:ing)?\b"
    r"|\bcross-?check(?:ing)?\s+confirms\b"
    r"|\bafter\s+(?:full|complete)\s+review\b"
    r"|\bfalse\s+positive\b"
    r"|\bactually\s+(?:is\s+)?present\b"
    r"|\bnot\s+an?\s+error\b"
    r"|\bis\s+present\s+in\s+(?:the\s+)?(?:einbauteilliste|montageteilliste)\b"
    # Reasoning/verification narrative that concludes there is no problem:
    r"|\bno\s+\w+\s+(?:issue|error|violation|mismatch|problem)s?\s+found\b"   # "no parts_label issue found"
    r"|[-–—]\s*consistent\b"                                                   # "… — consistent."
    r"|\b(?:is|are)\s+consistent\b"
    r"|\bafter\s+(?:a\s+)?(?:full|complete)\s+scan\b"
    r"|\band\s+(?:do(?:es)?\s+)?(?:appear|labell?ed)\b.{0,40}\bin\s+the\s+views\b",  # "… appear in the views"
    re.IGNORECASE | re.MULTILINE,
)

# Self-contradictory mismatch claims (e.g. "not listed" then "lists 08153 as …").
_SELF_CONTRADICTION_RE = re.compile(
    r"\bnot\s+listed\b.{0,220}\b(?:lists?|is\s+present)\b",
    re.IGNORECASE | re.DOTALL,
)

_REASONING_SUFFIX_RE = re.compile(
    r"\s*[-–—]\s*(?:re-?check(?:ing)?|re-?evaluat\w*|cross-?check(?:ing)?|after\s+.+)$",
    re.IGNORECASE,
)

_VERDICT_PREFIX_RE = re.compile(r"^(?:PASS|FAIL|NOT\s+FOUND)\s*[—–-]\s*", re.IGNORECASE)

OUTPUT_RULES = """\
RULES — FINAL RESULT ONLY:
  • Put ONLY confirmed violations in issues[]. An empty issues[] means that check PASSED.
  • Add check keys to not_found when required drawing elements are missing — never assume PASS.
  • Issue descriptions state the violation fact only (label, value, location). Never include
    verification steps, re-checking, corrections, "no error", pass/fail verdicts, or items that
    turned out correct. If a suspected mismatch does not survive cross-check, omit it entirely.
  • PASS / FAIL / NOT FOUND are computed from your final issues[] — do not write them yourself.\
"""


class FindingLike(Protocol):
    severity: str
    description: str
    page: int
    location: str
    confidence: float


def is_valid_finding(description: str) -> bool:
    text = (description or "").strip()
    if not text:
        return False
    if _PASS_ITEM_RE.search(text):
        return False
    if _SELF_CONTRADICTION_RE.search(text):
        return False
    return True


def clean_finding_description(description: str) -> str:
    text = _VERDICT_PREFIX_RE.sub("", (description or "").strip())
    text = _REASONING_SUFFIX_RE.sub("", text).strip()
    return text


def accept_finding(description: str, confidence: float, threshold: float = 0.60) -> bool:
    return confidence >= threshold and is_valid_finding(description)


def fail_summary(count: int) -> str:
    if count <= 0:
        raise ValueError("fail_summary requires a positive violation count")
    suffix = "issue" if count == 1 else "issues"
    return f"FAIL — {count} {suffix} found."


def build_check_issues(
    category: str,
    check_meta: dict[str, tuple[str, str, str]],
    by_check: dict[str, list[FindingLike]],
    not_found_set: set[str],
    enabled_sub: list[str] | None,
    dynamic_pass_descs: dict[str, str] | None = None,
) -> list[Issue]:
    """Assemble per-check PASS / FAIL / NOT FOUND summaries plus filtered findings."""
    issues: list[Issue] = []
    pass_overrides = dynamic_pass_descs or {}

    for check_key, (check_name, pass_desc, nf_desc) in check_meta.items():
        if enabled_sub is not None and check_key not in enabled_sub:
            continue

        if check_key in not_found_set:
            issues.append({
                "category": category,
                "check_name": check_name,
                "not_found": True,
                "severity": "info",
                "description": nf_desc,
                "page": 1,
                "location": "drawing",
                "confidence": 1.0,
            })
            continue

        found = by_check.get(check_key, [])
        passed = len(found) == 0
        summary_desc = pass_overrides.get(check_key, pass_desc) if passed else fail_summary(len(found))

        issues.append({
            "category": category,
            "check_name": check_name,
            "passed": passed,
            "severity": "info" if passed else "error",
            "description": summary_desc,
            "page": 1,
            "location": "drawing",
            "confidence": 1.0,
        })

        for item in found:
            issues.append({
                "category": category,
                "severity": item.severity,
                "description": clean_finding_description(item.description),
                "page": item.page,
                "location": item.location,
                "confidence": item.confidence,
            })

    return issues
