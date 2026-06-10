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
    not_found: bool     # True — only set when required drawing info was absent (check could not be performed)


class PDFContent(TypedDict, total=False):
    raw_text: str
    tables: list          # raw tables from pdfplumber: list[list[list[str|None]]]
    title_block: dict     # spatially extracted title block values
    formatted: str        # formatted text representation for LLM prompts


class _GraphStateRequired(TypedDict):
    pdf_path: str


class GraphState(_GraphStateRequired, total=False):
    enabled_checks: Optional[list[str]]             # subset of ["spell", "bend", "rebar"]
    enabled_sub_checks: Optional[dict[str, list[str]]]  # e.g. {"spell": ["spelling", ...]}
    pdf_data: Optional[str]               # base64-encoded PDF, used only in preprocess validation
    pdf_content: Optional[PDFContent]     # extracted content from pdfplumber, used by check nodes
    page_count: Optional[int]
    spell_issues: Optional[list[Issue]]
    bend_issues: Optional[list[Issue]]
    rebar_issues: Optional[list[Issue]]
    validation_results: Optional[dict]
    ui_response: Optional[dict]
