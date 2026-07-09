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


# Reference images attached to a check live next to its .md file:
#   <root>/<domain>/<key>/images/<filename>
IMAGE_MEDIA_TYPES = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}


def writable_images_dir(domain: str, key: str) -> Path:
    """Directory for saving a check's reference images (created on demand)."""
    path = writable_knowledge_dir() / domain / key / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_check_image_paths(domain: str, key: str) -> list[Path]:
    """All reference images attached to a check, across knowledge roots.

    Writable overlay wins on filename collision (same rule as the .md files).
    """
    seen: dict[str, Path] = {}
    for root in knowledge_roots():
        images_dir = root / domain / key / "images"
        if not images_dir.is_dir():
            continue
        for p in sorted(images_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in IMAGE_MEDIA_TYPES and p.name not in seen:
                seen[p.name] = p
    return [seen[name] for name in sorted(seen)]
