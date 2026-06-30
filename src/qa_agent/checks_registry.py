"""Discover, read, and persist QA check definitions stored as .md files.

Every check lives at ``QA Knowledge/<domain>/<key>/<key>.md`` with the sections
the retriever reads (Display Name / Pass / Not Found / Description / Check Prompt).

Shipped built-in checks are listed in ``SHIPPED_BUILTIN_KEYS``. User-defined checks
can be created in any domain (spell / bend / rebar) from the Define Rules UI and are
executed as AI prose rules during analysis.
"""
from __future__ import annotations

import re
import shutil

from qa_agent.rag import retriever
from qa_agent.rag.retriever import _KNOWLEDGE_DIR, _read_md_section

BUILTIN_DOMAINS = ["spell", "bend", "rebar"]
ALL_DOMAINS = BUILTIN_DOMAINS
COMING_SOON_DOMAINS = frozenset({"bend", "rebar"})

SHIPPED_BUILTIN_KEYS: dict[str, frozenset[str]] = {
    "spell": frozenset({
        "spelling", "section_name", "parts_label", "pos_count", "revision_check",
        "drawing_status", "exposition_class", "steel_content", "lastausgleich",
        "overview_plan_check", "steel_list_check",
    }),
    "bend": frozenset({
        "pos_coverage", "mesh_pos", "mesh_ratio", "mass_arithmetic",
        "bending_angle", "bar_length",
    }),
    "rebar": frozenset({
        "spacer_label", "pin_width_vertical", "pin_width_horizontal", "spacer_width",
    }),
}

_DOMAIN_TITLES = {
    "spell":  "Spelling & Title Block",
    "bend":   "Bending & Schedule",
    "rebar":  "Rebar Labels & Dims",
}

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")


def _md_path(domain: str, key: str):
    return _KNOWLEDGE_DIR / domain / key / f"{key}.md"


def is_builtin(domain: str, key: str) -> bool:
    return key in SHIPPED_BUILTIN_KEYS.get(domain, frozenset())


def slugify(name: str) -> str:
    """Turn a display name into a safe check key (lower snake_case)."""
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    if not s:
        s = "check"
    if not s[0].isalpha():
        s = f"c_{s}"
    return s[:48]


def _invalidate_caches() -> None:
    """Check prompts/meta are lru_cached — drop them so edits take effect live."""
    retriever.get_check_prompt.cache_clear()
    retriever.get_check_meta.cache_clear()
    retriever.get_check_requires_vision.cache_clear()
    retriever.get_check_debug_trace.cache_clear()


def read_check(domain: str, key: str) -> dict | None:
    path = _md_path(domain, key)
    if not path.exists():
        return None
    builtin = is_builtin(domain, key)
    rv_raw = _read_md_section(path, "Requires Vision").strip().lower()
    dt_raw = _read_md_section(path, "Debug Trace").strip().lower()
    return {
        "domain":           domain,
        "key":              key,
        "display_name":     _read_md_section(path, "Display Name") or key.replace("_", " ").title(),
        "pass":             _read_md_section(path, "Pass") or "PASS",
        "not_found":        _read_md_section(path, "Not Found") or "NOT FOUND",
        "description":      _read_md_section(path, "Description"),
        "prompt":           _read_md_section(path, "Check Prompt"),
        "requires_vision":  rv_raw in ("true", "yes", "1"),
        "debug_trace":      dt_raw in ("true", "yes", "1"),
        "builtin":          builtin,
        "user_defined":     not builtin,
    }


def list_domain_check_keys(domain: str) -> list[str]:
    domain_dir = _KNOWLEDGE_DIR / domain
    if not domain_dir.exists():
        return []
    return sorted(
        p.name for p in domain_dir.iterdir()
        if p.is_dir() and (p / f"{p.name}.md").exists()
    )


def list_user_ai_check_keys(domain: str) -> list[str]:
    """User-created checks in a domain — executed as AI prose rules."""
    return [k for k in list_domain_check_keys(domain) if not is_builtin(domain, k)]


def list_checks() -> list[dict]:
    """All checks across every domain."""
    out: list[dict] = []
    for domain in ALL_DOMAINS:
        for key in list_domain_check_keys(domain):
            check = read_check(domain, key)
            if check:
                out.append(check)
    return out


def domain_title(domain: str) -> str:
    return _DOMAIN_TITLES.get(domain, domain.title())


def _render_md(check: dict) -> str:
    rv = "true" if check.get("requires_vision") else "false"
    dt = "true" if check.get("debug_trace") else "false"
    return (
        f"# {check['display_name']}\n\n"
        f"> **Domain:** {check['domain']} | **Check key:** `{check['key']}`\n\n"
        f"## Display Name\n\n{check['display_name']}\n\n"
        f"## Pass\n\n{check['pass']}\n\n"
        f"## Not Found\n\n{check['not_found']}\n\n"
        f"## Requires Vision\n\n{rv}\n\n"
        f"## Debug Trace\n\n{dt}\n\n"
        f"## Description\n\n{check.get('description', '')}\n\n"
        f"## Check Prompt\n\n{check['prompt']}\n"
    )


def save_check(
    *, domain: str, key: str | None, display_name: str, description: str,
    prompt: str, pass_text: str, not_found_text: str,
    requires_vision: bool = False,
    debug_trace: bool | None = None,
) -> dict:
    """Create or overwrite a check .md. Built-in checks may be edited in place;
    new checks can be created in any domain. Returns the saved check."""
    domain = (domain or "spell").strip().lower()
    if domain not in ALL_DOMAINS:
        raise ValueError(f"Unknown domain: {domain!r}")

    key = (key or "").strip().lower() or slugify(display_name)
    if not _KEY_RE.match(key):
        raise ValueError(
            "Invalid check key — use lowercase letters, digits and underscores "
            "(must start with a letter)."
        )

    is_new = not _md_path(domain, key).exists()
    if is_new and is_builtin(domain, key):
        raise ValueError(f"Check key {key!r} is reserved for a built-in check.")
    if is_new and not (prompt or description or "").strip():
        raise ValueError("A new check needs a description or Check Prompt.")

    effective_prompt = (prompt or description or "").strip()
    is_user = not is_builtin(domain, key)
    if debug_trace is None:
        if is_new and is_user:
            debug_trace = True
        else:
            existing = read_check(domain, key)
            debug_trace = bool(existing and existing.get("debug_trace"))
    check = {
        "domain":           domain,
        "key":              key,
        "display_name":     (display_name or key.replace("_", " ").title()).strip(),
        "description":      (description or "").strip(),
        "prompt":           effective_prompt,
        "pass":             (pass_text or "PASS").strip(),
        "not_found":        (not_found_text or "NOT FOUND").strip(),
        "requires_vision":  bool(requires_vision),
        "debug_trace":      bool(debug_trace),
        "builtin":          is_builtin(domain, key),
        "user_defined":     is_user,
    }

    path = _md_path(domain, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_md(check), encoding="utf-8")
    _invalidate_caches()
    if check.get("debug_trace"):
        from qa_agent.extraction.evaluators import DETERMINISTIC_EVALUATORS
        print(
            f"[checks_registry] saved {domain}/{key} with debug_trace=true "
            f"(deterministic={key in DETERMINISTIC_EVALUATORS})"
        )
    return check


def delete_check(domain: str, key: str) -> None:
    """Delete a user-defined check. Built-in checks cannot be deleted."""
    domain = (domain or "").strip().lower()
    if domain not in ALL_DOMAINS:
        raise ValueError(f"Unknown domain: {domain!r}")
    if is_builtin(domain, key):
        raise ValueError("Built-in checks cannot be deleted.")
    folder = _md_path(domain, key).parent
    if folder.exists():
        shutil.rmtree(folder)
    _invalidate_caches()
