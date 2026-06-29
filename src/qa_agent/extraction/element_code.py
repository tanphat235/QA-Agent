"""Element-code parsing helpers (e.g. '201-851' from Drawing Title suffix)."""
from __future__ import annotations

import re

_ELEMENT_CODE_RE = re.compile(r"\d+[A-Z]{0,2}-\d+", re.IGNORECASE)
_ELEMENT_CODE_EXACT_RE = re.compile(r"^\d+[A-Z]{0,2}-\d+$", re.IGNORECASE)
_LINE_SNAP = 4


def parse_element_code_suffix(text: str | None) -> str | None:
    """Return the last element-code token (e.g. '201-851') from a title string."""
    if not text:
        return None
    codes = _ELEMENT_CODE_RE.findall(text)
    return codes[-1].upper() if codes else None


def normalize_element_code_token(text: str) -> str | None:
    """Normalize a token/line to an element code, tolerating spaces around '-'."""
    s = (text or "").strip()
    if not s:
        return None
    compact = re.sub(r"\s+", "", s)
    if _ELEMENT_CODE_EXACT_RE.fullmatch(compact):
        return compact.upper()
    return parse_element_code_suffix(s)


def find_drawing_title_in_raw(raw_text: str) -> str | None:
    """Best-effort Drawing Title from raw text (title-block area only)."""
    for label_pat in (
        r"(?:Bezeichnung|Drawing Title)[^\n]{0,40}\n\s*([^\n]{5,120})",
        r"(?:Bezeichnung|Drawing Title)[^\n:]{0,20}:\s*([^\n:]{5,120})",
    ):
        m = re.search(label_pat, raw_text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def resolve_element_code_from_title(title_block: dict, raw_text: str) -> str | None:
    """Parse element-code suffix from title block fields or raw text near the label."""
    for src in (
        title_block.get("drawing_title_value"),
        title_block.get("drawing_name"),
        find_drawing_title_in_raw(raw_text),
    ):
        code = parse_element_code_suffix(str(src) if src else None)
        if code:
            return code

    for anchor in ("Drawing Title", "Bezeichnung", "Formwork and reinforcement", "Schalung"):
        idx = raw_text.lower().rfind(anchor.lower())
        if idx >= 0:
            snippet = raw_text[idx: idx + 300]
            codes = _ELEMENT_CODE_RE.findall(snippet)
            if codes:
                return codes[-1].upper()
    return None


def find_top_left_element_code_raw(raw_text: str) -> str | None:
    """Fallback: scan the top of extracted text for a standalone element code."""
    head = raw_text[:2000]
    for line in head.split("\n"):
        line = line.strip()
        if not line:
            continue
        code = normalize_element_code_token(line)
        if code and len(line) <= 20:
            return code

    codes = _ELEMENT_CODE_RE.findall(head)
    return codes[0].upper() if codes else None


def find_top_left_element_code(
    words: list[dict],
    page_width: float,
    page_height: float,
    raw_text: str = "",
) -> str | None:
    """Element code at the top-left of the sheet (e.g. '201-851')."""
    x_max = page_width * 0.50
    y_max = page_height * 0.35
    in_corner = [w for w in words if w["x0"] <= x_max and w["top"] <= y_max]

    if in_corner:
        exact = [
            (w["top"], w["x0"], w["text"].strip().upper())
            for w in in_corner
            if normalize_element_code_token(w["text"].strip())
            and _ELEMENT_CODE_EXACT_RE.fullmatch(re.sub(r"\s+", "", w["text"].strip()))
        ]
        if exact:
            return min(exact, key=lambda t: (t[0], t[1]))[2]

        in_corner.sort(key=lambda w: (w["top"], w["x0"]))
        lines: list[str] = []
        current_words: list[str] = []
        current_y: float = in_corner[0]["top"]
        for w in in_corner:
            if abs(w["top"] - current_y) <= _LINE_SNAP:
                current_words.append(w["text"])
            else:
                lines.append(" ".join(current_words).strip())
                current_words = [w["text"]]
                current_y = w["top"]
        if current_words:
            lines.append(" ".join(current_words).strip())

        for line in sorted(lines, key=lambda ln: (len(ln), ln)):
            code = normalize_element_code_token(line)
            if code and len(line) <= 24:
                return code

    return find_top_left_element_code_raw(raw_text)


def resolve_drawing_codes(title_block: dict, raw_text: str) -> tuple[str | None, str | None]:
    """Return (top_left_code, title_suffix_code) with runtime fallbacks."""
    top = (title_block.get("element_code_top_left") or "").strip()
    from_title = (title_block.get("element_code_from_title") or "").strip()

    if not from_title:
        from_title = (resolve_element_code_from_title(title_block, raw_text) or "").strip()
    if not top:
        top = (normalize_element_code_token(title_block.get("drawing_name") or "") or "").strip()
    if not top:
        top = (find_top_left_element_code_raw(raw_text) or "").strip()
    if not from_title:
        from_title = (parse_element_code_suffix(title_block.get("drawing_title_value")) or "").strip()
    if not top and from_title:
        for line in raw_text[:2000].split("\n"):
            code = normalize_element_code_token(line.strip())
            if code and code.upper() == from_title.upper():
                top = code
                break

    return (top or None, from_title or None)
