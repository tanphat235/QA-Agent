"""Resolve shipped vs writable QA Knowledge directories.

Built-in checks ship in the repo under ``QA AI Drawing/QA Knowledge``.
User-defined checks are written to a writable overlay (``/tmp`` on Vercel).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

BUILTIN_KNOWLEDGE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "QA AI Drawing"
    / "QA Knowledge"
)


def writable_knowledge_dir() -> Path:
    """Directory for user-created / edited check .md files."""
    custom = os.getenv("QA_CHECKS_DATA_DIR", "").strip()
    if custom:
        return Path(custom)
    return Path(tempfile.gettempdir()) / "qa-agent-knowledge"


def resolve_md_path(domain: str, key: str) -> Path | None:
    """Return the .md path to read — overlay overrides built-in."""
    overlay = writable_knowledge_dir() / domain / key / f"{key}.md"
    if overlay.is_file():
        return overlay
    builtin = BUILTIN_KNOWLEDGE_DIR / domain / key / f"{key}.md"
    if builtin.is_file():
        return builtin
    return None


def writable_md_path(domain: str, key: str) -> Path:
    """Path for saving a user check (always under the writable overlay)."""
    path = writable_knowledge_dir() / domain / key / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def knowledge_roots() -> list[Path]:
    """Roots to scan when listing checks (writable first)."""
    roots = [writable_knowledge_dir()]
    if BUILTIN_KNOWLEDGE_DIR not in roots:
        roots.append(BUILTIN_KNOWLEDGE_DIR)
    return roots
