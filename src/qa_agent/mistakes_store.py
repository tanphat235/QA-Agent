"""
Structured AI mistakes store.
Source of truth: qa_ai_mistakes.json
Compiled output:  qa_ai_common_mistakes.txt  (read by the RAG retriever)
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

_QA_DIR    = Path(__file__).parent.parent.parent / "QA AI Drawing" / "QA Knowledge"
_JSON_PATH = _QA_DIR / "qa_ai_mistakes.json"
_TXT_PATH  = _QA_DIR / "qa_ai_common_mistakes.txt"

_sep_thick = "═" * 63
_sep_thin  = "━" * 42

_section_detect: list[tuple[str, str]] = [
    ("BENDING",  "bend"),
    ("SPELLING", "spell"),
    ("REBAR",    "rebar"),
]
_section_markers = {"CHECK", "SCHEDULE", "LABEL", "DIMENSION"}

SECTIONS: dict[str, str] = {
    "bend":  "Bending & Schedule Checks",
    "spell": "Spelling & Title Block Checks",
    "rebar": "Rebar Label & Dimension Checks",
}

CHECKS: dict[str, list[tuple[str, str]]] = {
    "bend": [
        ("pos_count",       "Last Position Number vs Title Block"),
        ("pos_coverage",    "Pos Coverage"),
        ("mesh_pos",        "Mesh Reinforcement Pos"),
        ("mesh_ratio",      "Mesh-to-Total Mass Ratio"),
        ("mass_arithmetic", "Total Mass Arithmetic"),
        ("bending_angle",   "Bending Angle / Mandrel Diameter"),
        ("bar_length",      "Bar Length vs Schedule"),
    ],
    "spell": [
        ("spelling",         "Spelling"),
        ("section_name",     "Section Name Completeness"),
        ("component_name",   "Component Name vs Title Block"),
        ("section_scale",    "Scale Consistency"),
        ("grid_lines",       "Grid Lines Consistency"),
        ("parts_lists",      "Parts Lists Present"),
        ("parts_quantities", "Parts Quantities"),
        ("parts_labels",     "Built-in Part Labels"),
        ("3d_view",          "3D View"),
        ("drawing_title",    "Drawing Title vs Title Block"),
    ],
    "rebar": [
        ("spacer_label",         "Spacer/Clamp Label Suffix"),
        ("pin_width_vertical",   "Vertical Pin Width"),
        ("pin_width_horizontal", "Horizontal Pin Width"),
        ("spacer_width",         "Spacer/Clamp Width"),
    ],
}

_keyword_map: list[tuple[str, str, str]] = [
    ("Pos Coverage",             "bend",  "pos_coverage"),
    ("Last Position Number",     "bend",  "pos_count"),
    ("letzte Stabstahlposition", "bend",  "pos_count"),
    ("Total Mass",               "bend",  "mass_arithmetic"),
    ("Bending Angle",            "bend",  "bending_angle"),
    ("3D View",                  "spell", "3d_view"),
    ("Section Name",             "spell", "section_name"),
    ("Parts Quantities",         "spell", "parts_quantities"),
    ("Built-in Part Labels",     "spell", "parts_labels"),
    ("Spacer/Clamp Label",       "rebar", "spacer_label"),
    ("Pin/Spacer",               "rebar", "pin_width_vertical"),
    ("Vertical vs Horizontal",   "rebar", "pin_width_vertical"),
]


def _infer_check_key(title: str, section_key: str) -> str:
    for keyword, s, ck in _keyword_map:
        if keyword.lower() in title.lower() and s == section_key:
            return ck
    return "general"


def _detect_section(stripped: str) -> str | None:
    """Return section key if the line is a section heading, else None."""
    up = stripped.upper()
    if not any(m in up for m in _section_markers):
        return None
    for kw, sk in _section_detect:
        if kw in up:
            return sk
    return None


def _flush(current: dict, section: str | None, data: dict) -> None:
    """Append the accumulated mistake to data, then clear current."""
    if current and section and "title" in current:
        data[section].append({
            "id":        str(uuid.uuid4()),
            "check_key": _infer_check_key(current["title"], section),
            "title":     current["title"],
            "wrong":     " ".join(current.get("wrong_parts",   [])),
            "correct":   " ".join(current.get("correct_parts", [])),
        })
    current.clear()


def _apply_content_line(line: str, stripped: str, current: dict, state: str | None) -> str | None:
    """Update current mistake from a content line; return new state."""
    if stripped.startswith("WRONG:"):
        text = stripped[6:].strip()
        if text:
            current.setdefault("wrong_parts", []).append(text)
        return "wrong"
    if re.match(r"^CORRECT[\s:—]", stripped):
        text = re.sub(r"^CORRECT\s*[:\s—]\s*", "", stripped).strip()
        if text:
            current.setdefault("correct_parts", []).append(text)
        return "correct"
    if stripped and line.startswith(" ") and state in ("wrong", "correct"):
        key = "wrong_parts" if state == "wrong" else "correct_parts"
        current.setdefault(key, []).append(stripped)
    return state


def _parse_txt(txt: str) -> dict[str, list]:
    """Migrate existing plain-text file into the structured JSON format."""
    data: dict[str, list] = {"bend": [], "spell": [], "rebar": []}
    current: dict = {}
    section: str | None = None
    state: str | None = None

    for line in txt.splitlines():
        stripped = line.strip()
        found_sec = _detect_section(stripped)
        if found_sec:
            _flush(current, section, data)
            section, state = found_sec, None
        elif stripped.startswith("[MISTAKE]"):
            _flush(current, section, data)
            current = {"title": stripped[9:].strip(), "wrong_parts": [], "correct_parts": []}
            state = "title"
        else:
            state = _apply_content_line(line, stripped, current, state)

    _flush(current, section, data)
    return data


def _compile_check_group(ck: str, title_map: dict, items: list) -> list[str]:
    """Compile one check's mistakes into text lines."""
    out = [f"[CHECK: {title_map.get(ck, ck)}]", ""]
    for item in items:
        title   = item.get("title",   "").strip()
        wrong   = item.get("wrong",   "").strip()
        correct = item.get("correct", "").strip()
        out.append(f"[MISTAKE] {title}")
        if wrong:
            out.append(f"  WRONG: {wrong}")
        if correct:
            out.append(f"  CORRECT: {correct}")
        out.append("")
    return out


def _compile_section(section_key: str, section_title: str, items: list) -> list[str]:
    """Compile one section into text lines."""
    out: list[str] = ["", _sep_thin, section_title.upper(), _sep_thin, ""]

    by_check: dict[str, list] = {}
    for item in items:
        by_check.setdefault(item.get("check_key", "general"), []).append(item)

    title_map    = dict(CHECKS.get(section_key, []))
    defined_keys = [k for k, _ in CHECKS.get(section_key, [])]
    extra_keys   = [k for k in by_check if k not in defined_keys]

    for ck in defined_keys + extra_keys:
        if ck in by_check:
            out.extend(_compile_check_group(ck, title_map, by_check[ck]))

    if not by_check:
        out += ["(no mistakes recorded for this section)", ""]

    return out


def _compile_txt(data: dict[str, list]) -> str:
    """Compile structured data to the plain-text format injected into AI prompts."""
    out: list[str] = [
        _sep_thick,
        "KNOWN AI CHECK MISTAKES — READ BEFORE MAKING ANY JUDGEMENT",
        "These are real cases where the AI previously checked incorrectly.",
        "Use them to avoid the same errors.",
        _sep_thick,
    ]
    for section_key, section_title in SECTIONS.items():
        out.extend(_compile_section(section_key, section_title, data.get(section_key, [])))
    return "\n".join(out)


def load_structured() -> dict:
    """Load the structured mistakes JSON, migrating from txt on first run."""
    if _JSON_PATH.exists():
        return json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    raw = _TXT_PATH.read_text(encoding="utf-8") if _TXT_PATH.exists() else ""
    data: dict = _parse_txt(raw) if raw else {"bend": [], "spell": [], "rebar": []}
    _JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def save_structured(data: dict) -> None:
    """Persist structured data to JSON and recompile the txt file."""
    _JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _TXT_PATH.write_text(_compile_txt(data), encoding="utf-8")
