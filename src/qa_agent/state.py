from __future__ import annotations
from typing import Optional
from typing_extensions import TypedDict


class _IssueBase(TypedDict):
    category: str    # "spell" | "bend" | "rebar"
    severity: str    # "error" | "warning" | "info"
    description: str
    page: int
    location: str
    confidence: float


class Issue(_IssueBase, total=False):
    passed: bool        # True/False — only set on per-check summary items
    check_name: str     # Name of the check area — only set on summary items


class PDFContent(TypedDict):
    raw_text: str
    tables: list[dict]
    page_count: int
    metadata: dict


class _GraphStateRequired(TypedDict):
    pdf_path: str


class GraphState(_GraphStateRequired, total=False):
    enabled_checks: Optional[list[str]]   # subset of ["spell", "bend", "rebar"]
    pdf_data: Optional[str]               # base64-encoded PDF, encoded once in preprocess
    page_count: Optional[int]
    spell_issues: Optional[list[Issue]]
    bend_issues: Optional[list[Issue]]
    rebar_issues: Optional[list[Issue]]
    validation_results: Optional[dict]
    ui_response: Optional[dict]
