"""Scale parsing — title block vs section view scales (e.g. M 1:25)."""
from __future__ import annotations

import re

_SCALE_TOKEN_RE = re.compile(r"(?:M\s*)?1\s*:\s*(\d+)", re.IGNORECASE)
_TITLE_LABEL_RE = re.compile(r"(?:Maßstab|Massstab|Scale)", re.IGNORECASE)

# View titles that carry a scale label (section / elevation / named detail).
_VIEW_TITLE_RE = re.compile(
    r"\b(?:"
    r"Schnitt\s+[A-Za-z0-9][\w\-–/]*(?:\s*/\s*Section\s+[A-Za-z0-9][\w\-–]*)?"
    r"|Section\s+[A-Za-z0-9][\w\-–]+"
    r"|Ansicht\s+[A-Za-z0-9][\w\-–]+"
    r"|Draufsicht(?:\s+[A-Za-z0-9][\w\-–/]*(?:\s*/\s*Top\s+view\s+[A-Za-z0-9][\w\-–]*)?)?"
    r"|Querschnitt\s+[A-Za-z0-9][\w\-–]+"
    r")\b",
    re.IGNORECASE,
)

# Named detail views only — not loose "general detail" prose.
_DETAIL_TITLE_RE = re.compile(
    r"\bDetail\s+(?:\d+(?:\.\d+)?|[A-Za-z]\b)",
    re.IGNORECASE,
)

# Full-text: Schnitt/Section id then scale within a short window.
_VIEW_SCALE_CHUNK_RE = re.compile(
    r"(Schnitt\s+[A-Za-z0-9][\w\-–/]*(?:\s*/\s*Section\s+[A-Za-z0-9][\w\-–]*)?"
    r"|Section\s+[A-Za-z0-9][\w\-–]+"
    r"|Ansicht\s+[A-Za-z0-9][\w\-–]+"
    r"|Querschnitt\s+[A-Za-z0-9][\w\-–]+)"
    r"[^\n]{0,160}?"
    r"((?:M\s*)?1\s*:\s*\d+)",
    re.IGNORECASE,
)

_VIEW_ID_RE = re.compile(r"^[A-Za-z0-9][\w\-–]+$")
_ROTATED_MARKER = "=== ROTATED / VERTICAL LABELS"


def normalize_scale_token(text: str | None) -> str | None:
    """Normalize 'M 1:25' / '1:25' to canonical '1:25'."""
    if not text:
        return None
    m = _SCALE_TOKEN_RE.search(text)
    if not m:
        return None
    return f"1:{m.group(1)}"


def extract_all_scale_tokens(text: str | None) -> list[str]:
    """Return every distinct scale ratio in text, in reading order (e.g. '1:25 1:10 1:5')."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _SCALE_TOKEN_RE.finditer(text):
        s = f"1:{m.group(1)}"
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _main_body_text(raw_text: str) -> str:
    """Drop rotated-label dump so scales there are not double-counted."""
    idx = raw_text.find(_ROTATED_MARKER)
    return raw_text[:idx] if idx >= 0 else raw_text


def _scan_lines_for_scale(lines: list[str], start: int, *, max_ahead: int = 6) -> tuple[str | None, str]:
    for offset in range(max_ahead):
        idx = start + offset
        if idx >= len(lines):
            break
        scale = normalize_scale_token(lines[idx])
        if scale:
            source = "same_line" if offset == 0 else f"line+{offset}"
            return scale, source
    return None, ""


def _label_dedup_key(label: str) -> str:
    s = re.sub(r"\s+", " ", (label or "").strip().lower())
    # Collapse bilingual Schnitt a-a/Section a-a to one key per cut id.
    m = re.search(r"(?:schnitt|section)\s+([a-z0-9][\w\-–]*)", s, re.IGNORECASE)
    if m:
        return f"cut:{m.group(1).lower()}"
    m = re.search(r"ansicht\s+([a-z0-9][\w\-–]*)", s, re.IGNORECASE)
    if m:
        return f"ansicht:{m.group(1).lower()}"
    return s[:80]


def _append_section(
    sections: list[dict],
    seen: set[str],
    *,
    label: str,
    scale: str,
    source: str,
    line: int | None = None,
) -> None:
    key = _label_dedup_key(label)
    if key in seen:
        return
    seen.add(key)
    sections.append({
        "label": label.strip()[:120],
        "scale": scale,
        "line": line,
        "source": source,
    })


def _find_section_scales_line_based(raw_text: str) -> list[dict]:
    """Line scan: view title on a line, scale on same line or up to 5 lines below."""
    sections: list[dict] = []
    seen: set[str] = set()
    body = _main_body_text(raw_text)
    lines = body.split("\n")

    for i, line in enumerate(lines):
        is_view = bool(_VIEW_TITLE_RE.search(line)) or bool(_DETAIL_TITLE_RE.search(line))
        if not is_view:
            continue
        scale, source = _scan_lines_for_scale(lines, i, max_ahead=6)
        if scale:
            _append_section(
                sections, seen,
                label=line, scale=scale, source=source, line=i + 1,
            )
    return sections


def _find_section_scales_regex(raw_text: str, seen: set[str]) -> list[dict]:
    """Regex over full text — catches bilingual titles and nearby scales."""
    sections: list[dict] = []
    body = _main_body_text(raw_text)
    for m in _VIEW_SCALE_CHUNK_RE.finditer(body):
        label = m.group(1).strip()
        scale = normalize_scale_token(m.group(2))
        if not scale:
            continue
        _append_section(sections, seen, label=label, scale=scale, source="regex")
    return sections


def _row_words(words: list[dict], anchor: dict, *, y_tol: float = 10) -> list[dict]:
    ay = (anchor["top"] + anchor["bottom"]) / 2
    return sorted(
        [
            w for w in words
            if abs((w["top"] + w["bottom"]) / 2 - ay) <= y_tol
            and w["x0"] >= anchor["x0"] - 8
        ],
        key=lambda w: w["x0"],
    )


def _is_view_anchor(anchor: dict, row: list[dict]) -> bool:
    t = anchor["text"].strip()
    if re.fullmatch(r"Schnitt", t, re.IGNORECASE):
        return True
    if re.fullmatch(r"Ansicht", t, re.IGNORECASE):
        return True
    if re.fullmatch(r"Querschnitt", t, re.IGNORECASE):
        return True
    if re.fullmatch(r"Section", t, re.IGNORECASE):
        # Require a view id on the same row (e.g. a-a, b-b).
        idx = next((i for i, w in enumerate(row) if w is anchor), -1)
        if idx >= 0 and idx + 1 < len(row):
            nxt = row[idx + 1]["text"].strip()
            return bool(_VIEW_ID_RE.match(nxt))
        return False
    return False


def _scale_near_anchor(anchor: dict, words: list[dict]) -> tuple[str | None, str]:
    ax0, ax1 = anchor["x0"], anchor["x1"]
    ay = (anchor["top"] + anchor["bottom"]) / 2
    col_slack = 80

    # Same row, to the right of the title.
    same_row = sorted(
        [
            w for w in words
            if _SCALE_TOKEN_RE.search(w["text"])
            and abs((w["top"] + w["bottom"]) / 2 - ay) <= 12
            and w["x0"] >= ax0 - 10
        ],
        key=lambda w: w["x0"],
    )
    for w in same_row:
        if w["x0"] >= ax1 - 15 or len(same_row) == 1:
            scale = normalize_scale_token(w["text"])
            if scale:
                return scale, "words_same_row"

    # Below the title (typical: scale under Schnitt label).
    below = sorted(
        [
            w for w in words
            if _SCALE_TOKEN_RE.search(w["text"])
            and w["top"] > anchor["bottom"] - 2
            and w["top"] <= anchor["bottom"] + 140
            and w["x0"] >= ax0 - col_slack
            and w["x0"] <= ax1 + col_slack
        ],
        key=lambda w: (w["top"], w["x0"]),
    )
    if below:
        scale = normalize_scale_token(below[0]["text"])
        if scale:
            return scale, "words_below"

    return None, ""


def _find_section_scales_from_words(words: list[dict], seen: set[str]) -> list[dict]:
    """Spatial match: every Schnitt/Section/Ansicht anchor on the sheet."""
    sections: list[dict] = []
    if not words:
        return sections

    for anchor in words:
        row = _row_words(words, anchor)
        if not _is_view_anchor(anchor, row):
            continue
        label = " ".join(w["text"] for w in row[:10]).strip()
        if len(label) < 4:
            continue
        scale, source = _scale_near_anchor(anchor, words)
        if not scale:
            continue
        _append_section(sections, seen, label=label, scale=scale, source=source)
    return sections


def find_section_scales(raw_text: str, words: list[dict] | None = None) -> list[dict]:
    """All section/elevation/detail view scales on the drawing sheet."""
    seen: set[str] = set()
    sections: list[dict] = []

    for item in _find_section_scales_line_based(raw_text):
        key = _label_dedup_key(item["label"])
        if key not in seen:
            seen.add(key)
            sections.append(item)

    sections.extend(_find_section_scales_regex(raw_text, seen))
    sections.extend(_find_section_scales_from_words(words or [], seen))

    sections.sort(key=lambda s: (s.get("line") or 9999, s.get("label", "")))
    return sections


def _scales_near_title_label(label: dict, words: list[dict]) -> list[str]:
    """Collect every scale on the same row as Maßstab/Scale and the line below."""
    ly = (label["top"] + label["bottom"]) / 2
    scales: list[str] = []
    seen: set[str] = set()
    for w in words:
        if not _SCALE_TOKEN_RE.search(w["text"]):
            continue
        wy = (w["top"] + w["bottom"]) / 2
        same_row = abs(wy - ly) <= 14
        below = label["bottom"] - 2 <= w["top"] <= label["bottom"] + 55
        if not (same_row or below):
            continue
        if w["x0"] < label["x0"] - 40:
            continue
        s = normalize_scale_token(w["text"])
        if s and s not in seen:
            seen.add(s)
            scales.append(s)
    return scales


def find_title_block_scales(raw_text: str, words: list[dict] | None = None) -> list[str]:
    """All scales listed under Scale / Maßstab in the title block (e.g. 1:25 1:10 1:5)."""
    tail = raw_text[int(len(raw_text) * 0.45) :]
    scales: list[str] = []
    seen: set[str] = set()

    for pat in (
        r"(?:Scale\s*/\s*Maßstab|Scale\s*/\s*Massstab|Maßstab|Massstab|Scale)\s*:?\s*([^\n]{1,80})",
        r"(?:Maßstab|Massstab|Scale)\s*[:\n]\s*([^\n]{1,80})",
    ):
        for m in re.finditer(pat, tail, re.IGNORECASE):
            for s in extract_all_scale_tokens(m.group(1)):
                if s not in seen:
                    seen.add(s)
                    scales.append(s)

    if words:
        label_hits = [w for w in words if _TITLE_LABEL_RE.search(w["text"])]
        for label in sorted(label_hits, key=lambda w: w["top"], reverse=True):
            for s in _scales_near_title_label(label, words):
                if s not in seen:
                    seen.add(s)
                    scales.append(s)

    return scales


def find_title_block_scale(raw_text: str, words: list[dict] | None = None) -> str | None:
    """Primary (first) title-block scale — backward-compatible helper."""
    scales = find_title_block_scales(raw_text, words)
    return scales[0] if scales else None


def resolve_scales(title_block: dict, raw_text: str, words: list[dict] | None = None) -> dict:
    """Resolved title-block scale(s) and per-section scales for checks / debug trace."""
    title_blocks = title_block.get("scale_title_blocks") or find_title_block_scales(raw_text, words)
    sections = title_block.get("scale_sections") or find_section_scales(raw_text, words)
    return {
        "title_block": title_blocks[0] if title_blocks else None,
        "title_blocks": title_blocks,
        "sections": sections,
    }
