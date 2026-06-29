"""Public API — PDF extraction data for user-defined checks.

User-defined checks should ONLY consume data from this module:
  • build_extraction_context(state)  — structured fields from pdfplumber
  • format_extraction_for_llm(ctx)   — text block for LLM prompts
  • run_deterministic_check(key, …)  — Python evaluators (no LLM)
  • list_extraction_fields()         — catalog for frontend

Low-level PDF parsing lives in qa_agent.nodes.pdf_extractor (called at preprocess).
Do not re-export pdf_extractor here — that causes a circular import.
"""
from qa_agent.extraction.catalog import EXTRACTION_FIELDS, ExtractField, list_extraction_fields
from qa_agent.extraction.context import ExtractionContext, build_extraction_context
from qa_agent.extraction.evaluators import (
    DETERMINISTIC_EVALUATORS,
    DeterministicIssue,
    DeterministicResult,
    run_deterministic_check,
)
from qa_agent.extraction.format import format_extraction_for_llm

__all__ = [
    "EXTRACTION_FIELDS",
    "ExtractField",
    "ExtractionContext",
    "DETERMINISTIC_EVALUATORS",
    "DeterministicIssue",
    "DeterministicResult",
    "build_extraction_context",
    "format_extraction_for_llm",
    "list_extraction_fields",
    "run_deterministic_check",
]
