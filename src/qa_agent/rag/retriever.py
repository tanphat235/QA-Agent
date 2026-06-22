"""
Knowledge retrieval for QA check nodes.

All check knowledge lives in the .md files under QA Knowledge/.
This module provides cached readers — no pre-built cache file required.
"""
from __future__ import annotations

import base64
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_KNOWLEDGE_DIR = (
    Path(__file__).parent.parent.parent.parent
    / "QA AI Drawing" / "QA Knowledge"
)

_IMG_EXTS: dict[str, str] = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}


def _read_md_section(md_path: Path, section: str) -> str:
    """Extract the content of a ## Section from a markdown file."""
    if not md_path.exists():
        return ""
    text = md_path.read_text(encoding="utf-8")
    marker = f"## {section}"
    start = text.find(marker)
    if start == -1:
        return ""
    content = text[start + len(marker):].strip()
    next_sec = content.find("\n## ")
    return content[:next_sec].strip() if next_sec != -1 else content.strip()


@lru_cache(maxsize=None)
def get_check_prompt(domain: str, check_key: str) -> str:
    """Read the ## Check Prompt section from the check's .md file."""
    md_path = _KNOWLEDGE_DIR / domain / check_key / f"{check_key}.md"
    prompt = _read_md_section(md_path, "Check Prompt")
    if not prompt:
        logger.warning("No '## Check Prompt' in %s/%s/%s.md", domain, check_key, check_key)
    return prompt


@lru_cache(maxsize=None)
def get_check_meta(domain: str, check_key: str) -> tuple[str, str, str]:
    """Return (display_name, pass_desc, not_found_desc) from the check's .md file."""
    md_path = _KNOWLEDGE_DIR / domain / check_key / f"{check_key}.md"
    name  = _read_md_section(md_path, "Display Name") or check_key.replace("_", " ").title()
    pass_ = _read_md_section(md_path, "Pass")         or "PASS"
    nf    = _read_md_section(md_path, "Not Found")    or "NOT FOUND"
    return name, pass_, nf


@lru_cache(maxsize=None)
def get_check_requires_vision(domain: str, check_key: str) -> bool:
    """Return True if the check's .md declares '## Requires Vision: true'.

    Defaults to False — text-only checks run on the cheaper Haiku model.
    Vision checks receive the rendered PDF document and run on Sonnet.
    """
    md_path = _KNOWLEDGE_DIR / domain / check_key / f"{check_key}.md"
    val = _read_md_section(md_path, "Requires Vision").strip().lower()
    return val in ("true", "yes", "1")


@lru_cache(maxsize=None)
def get_node_images(domain: str) -> list[dict]:
    """
    Load all reference images for a domain from the knowledge filesystem.
    Returns Anthropic image content blocks. Cached in memory after first call.
    """
    domain_dir = _KNOWLEDGE_DIR / domain
    if not domain_dir.exists():
        return []
    images: list[dict] = []
    for img_file in sorted(domain_dir.rglob("*")):
        ext = img_file.suffix.lower()
        if ext not in _IMG_EXTS:
            continue
        data = base64.standard_b64encode(img_file.read_bytes()).decode()
        images.append({
            "type": "image",
            "source": {"type": "base64", "media_type": _IMG_EXTS[ext], "data": data},
        })
    return images
