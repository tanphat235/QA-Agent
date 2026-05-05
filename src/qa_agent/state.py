from __future__ import annotations
from typing import Optional
from typing_extensions import TypedDict


class Issue(TypedDict):
    category: str    # "spell" | "bend" | "rebar"
    severity: str    # "error" | "warning" | "info"
    description: str
    page: int
    location: str
    confidence: float


class PDFContent(TypedDict):
    raw_text: str
    tables: list[dict]
    page_count: int
    metadata: dict


class GraphState(TypedDict):
    pdf_path: str
    pdf_content: Optional[PDFContent]
    spell_issues: Optional[list[Issue]]
    bend_issues: Optional[list[Issue]]
    rebar_issues: Optional[list[Issue]]
    validation_results: Optional[dict]
    ui_response: Optional[dict]
