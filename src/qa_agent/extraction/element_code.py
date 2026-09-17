"""Element-code parsing helpers (e.g. '201-851' from Drawing Title suffix)."""
from __future__ import annotations

import re

# FALLBACK ONLY — element codes have no shape in common across projects, so the
# primary read is positional: find_top_left_element_code() takes whatever label
# the sheet prints in its corner, as printed. This pattern covers the two
# families seen so far and serves the paths that have no position to work from —
# pulling the code out of a Drawing Title suffix, or off a flat text dump:
#   "201-851", "202A-850"  — digits first, one dash
#   "ST-11-01"             — a letter prefix, then two numeric groups
# The letter form requires both numeric groups so it cannot swallow "FT-050"
# (the Unterlagennummer in a Plan-ID) or "ST-11" (the Statische Positionsnummer).
# A project whose codes look like neither still works through the corner read.
_CODE_ALTS = r"\d+[A-Z]{0,2}-\d+|[A-Z]{1,3}-\d{1,3}-\d{1,3}"

_ELEMENT_CODE_RE = re.compile(_CODE_ALTS, re.IGNORECASE)
_ELEMENT_CODE_EXACT_RE = re.compile(rf"^(?:{_CODE_ALTS})$", re.IGNORECASE)
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


def _corner_lines(
    words: list[dict], page_width: float, page_height: float,
) -> list[str]:
    """Text lines printed in the sheet's top-left corner, topmost first.

    Words outside the page are dropped: annotation and comment layers sit at
    negative coordinates and would otherwise come out ahead of the corner label.
    """
    in_corner = [
        w for w in words
        if 0 <= w["x0"] <= page_width * 0.25
        and 0 <= w["top"] <= page_height * 0.25
    ]
    if not in_corner:
        return []
    in_corner.sort(key=lambda w: (w["top"], w["x0"]))

    lines: list[str] = []
    current: list[str] = []
    current_y = in_corner[0]["top"]
    for w in in_corner:
        if abs(w["top"] - current_y) <= _LINE_SNAP:
            current.append(w["text"])
        else:
            lines.append(" ".join(current).strip())
            current = [w["text"]]
            current_y = w["top"]
    if current:
        lines.append(" ".join(current).strip())
    return [ln for ln in lines if ln]


def find_top_left_element_code(
    words: list[dict],
    page_width: float,
    page_height: float,
    raw_text: str = "",
) -> str | None:
    """The element code printed in the sheet's top-left corner.

    Read by POSITION, not by shape. Element codes have no structure in common
    across projects — "ST-11-01", "202-850", "ST-25-1NT-01" — so any pattern
    written to match one of them is tuned to whichever project was looked at
    last. The corner label is simply the first standalone short line in the
    corner, returned exactly as printed.

    The only constraint applied is one no element code fails and the things it
    must be told apart from do: it holds both a letter and a digit, which rules
    out a bare dimension ("1.20", "35") and a view title ("Ansicht"). Pattern
    matching survives only as the fallback for sheets whose corner label is not
    printed on a line of its own.
    """
    for line in _corner_lines(words, page_width, page_height):
        if len(line) > 24 or len(line.split()) > 2:
            continue
        if any(c.isdigit() for c in line) and any(c.isalpha() for c in line):
            return re.sub(r"\s+", "", line).upper()

    # Fallbacks for a corner that holds no standalone label: look for something
    # code-shaped there, then anywhere near the top of the extracted text.
    for line in _corner_lines(words, page_width, page_height):
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
