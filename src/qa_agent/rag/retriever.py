"""
Runtime retriever: loads the pre-built knowledge cache and returns
domain-specific reference context for injection into node prompts.

Usage in a node:
    from qa_agent.rag.retriever import get_node_context
    task_text = _TASK + get_node_context("bend")  # "" if cache not built
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent / "data" / "knowledge_cache.json"


@lru_cache(maxsize=1)
def _load_cache() -> dict:
    """Load knowledge cache once; subsequent calls return the cached dict."""
    if not _CACHE_PATH.exists():
        logger.warning(
            "RAG knowledge cache not found at %s — "
            "run: python -m qa_agent.rag.knowledge_builder",
            _CACHE_PATH,
        )
        return {}
    with open(_CACHE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    logger.info("RAG cache loaded: %d sample drawing(s).", len(data.get("sample_references", [])))
    return data


def get_node_context(domain: str) -> str:
    """
    Return a formatted reference context block to append to a node's task prompt.
    domain: "spell" | "bend" | "rebar"
    Returns "" if the knowledge cache has not been built yet (graceful degradation).
    """
    cache = _load_cache()
    if not cache:
        return ""

    parts: list[str] = []

    # 1. Rules extracted from the QA knowledge docx
    docx_text = cache.get("docx_knowledge", {}).get(domain, "")
    if docx_text:
        parts.append("QA KNOWLEDGE BASE RULES:\n" + docx_text)

    # 2. Reference patterns extracted from approved sample drawings
    ref_blocks: list[str] = []
    for entry in cache.get("sample_references", []):
        text = entry.get("domains", {}).get(domain, "")
        if text:
            ref_blocks.append(f"[Reference: {entry['filename']}]\n{text}")
    if ref_blocks:
        parts.append(
            "REFERENCE PATTERNS FROM APPROVED DRAWINGS:\n"
            + "\n\n".join(ref_blocks)
        )

    if not parts:
        return ""

    return (
        "\n\n═══════════════════════════════════\n"
        "RAG REFERENCE KNOWLEDGE\n"
        "(Use the rules and approved-drawing patterns below to calibrate your judgement.)\n"
        "═══════════════════════════════════\n"
        + "\n\n".join(parts)
    )
