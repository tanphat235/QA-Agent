"""Annotate a drawing PDF with the failed QA findings.

The returned file is the user's full imported PDF, unchanged, with the findings
appended into it as real PDF annotations (incremental save — the original bytes
are preserved verbatim and the notes are added on top).

Each failed finding is anchored to the place in the PDF where its offending text
appears: we pull candidate tokens out of the finding description (quoted values,
EBT/Pos codes, misspelled words, the location label) and search the page text
layer for them with PyMuPDF. A match becomes a coloured highlight carrying the
finding as a popup comment; findings whose text cannot be located are placed as
numbered sticky-note comments stacked in the page margin so nothing is lost.
"""
from __future__ import annotations

import os
import tempfile

import fitz  # PyMuPDF
import re

# Severity → highlight / note colour (RGB 0–1).
_SEVERITY_COLOR = {
    "ERROR":   (0.86, 0.15, 0.15),   # red
    "WARNING": (0.95, 0.61, 0.07),   # amber
}
_DEFAULT_COLOR = (0.86, 0.15, 0.15)

# Generic words that are useless as a search anchor (would match everywhere).
_STOPWORDS = {
    "drawing", "steel", "list", "title", "block", "value", "field", "mismatch",
    "found", "missing", "vs", "and", "the", "for", "not", "from", "with", "page",
    "empty", "none", "error", "warning", "misspelled", "spelling", "label",
    "note", "text", "wrong", "correct", "expected", "actual", "schnitt", "pos",
}

# Unicode → Latin-1 substitutions: PyMuPDF's built-in font draws Latin-1 only,
# so any text we *render* on the summary page must be folded down. (Annotation
# popup content is stored as UTF-16 and renders fine — only drawn text needs this.)
_TXT_REPL = {
    "—": "-", "–": "-", "→": "->", "←": "<-", "’": "'", "‘": "'",
    "“": '"', "”": '"', "•": "*", "×": "x", "≥": ">=", "≤": "<=", "²": "2", "³": "3",
    "Δ": "d", "∆": "d", "△": "d", "·": "-", "µ": "u", "Ø": "O", "ø": "o",
}


def _safe(text: str) -> str:
    """Fold drawn text down to Latin-1 so the built-in PDF font can render it."""
    s = text or ""
    for k, v in _TXT_REPL.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


# EBT/MT codes yield two anchors (bare number + labelled form), so handled apart.
_EBT_RE = re.compile(r"\b(EBT|MT)\s*0*(\d{2,6})\b", re.IGNORECASE)

# Each pattern has ONE capturing group; its matches become candidate anchors,
# tried longest-first. Ordered roughly most-specific → most-generic.
_TOKEN_PATTERNS = [
    re.compile(r"['‘’]([^'‘’]{2,80})['‘’]"),                       # 'quoted value'
    re.compile(r'["“”]([^"“”]{2,80})["“”]'),                       # "quoted value"
    re.compile(r"\bPos\.?\s*0*(\d{1,4})\b", re.IGNORECASE),         # Pos 12
    re.compile(r"([A-Za-zÄÖÜäöüß][\wÄÖÜäöüß./-]{2,})\s*(?:→|->|:)\s*\w"),  # wrong→correct
    re.compile(r"(\bSchnitt\s+[A-Z]-?[A-Z]?\b)"),                  # Schnitt A-A
    re.compile(r"(\b[A-ZÄÖÜ]{1,3}\d+(?:[/-][A-Z0-9]+)*\b)"),       # XC3, K38/17
    re.compile(r"(\b[A-ZÄÖÜ]{2,4}\b)"),                            # FV, KTL, V2A
    re.compile(r"(\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]{3,}\b)"),              # Jordahl, Wandansicht
]


def _search_tokens(description: str, location: str) -> list[str]:
    """Ordered, de-duplicated list of strings to look for in the page — most
    specific (longest / most unique) first."""
    desc = description or ""
    raw: list[str] = []
    for label, num in _EBT_RE.findall(desc):
        raw += [num, f"{label.upper()} {num}"]
    for pat in _TOKEN_PATTERNS:
        raw += pat.findall(desc)
    loc = _clean(location)
    if loc and len(loc) >= 4:
        raw.append(loc)
        # The field name inside a "title block X" / "drawing X" location is the
        # cleanest anchor (e.g. "Anzahl", "Gewicht", "BETONDECKUNG").
        m = re.match(r"(?:title\s*block|drawing)\b[\s/]*(.+)", loc, re.IGNORECASE)
        if m and len(m.group(1)) >= 3:
            raw.append(m.group(1))

    seen: set[str] = set()
    ordered: list[str] = []
    for tok in raw:
        t = _clean(tok)
        if len(t) < 2 or t.lower() in _STOPWORDS or t.lower() in seen:
            continue
        seen.add(t.lower())
        ordered.append(t)

    ordered.sort(key=len, reverse=True)   # longest = most specific anchor wins
    return ordered


def _find_rect(
    page: "fitz.Page", tokens: list[str], prefer_bottom: bool = False,
) -> "fitz.Rect | None":
    """First token that matches wins. When prefer_bottom is set (title-block
    findings), pick the lowest occurrence on the page — the title block is the
    bottom-most element, so this skips identical labels in the body / schedules."""
    for tok in tokens:
        try:
            hits = page.search_for(tok, quads=False)
        except Exception:
            hits = []
        if hits:
            return max(hits, key=lambda r: r.y0) if prefer_bottom else hits[0]
    return None


def _page_index(raw_page: object, page_count: int) -> int:
    try:
        p = int(raw_page)
    except (TypeError, ValueError):
        p = 1
    p = max(1, min(p, page_count))   # findings use 1-based pages
    return p - 1


def _add_comment(annot: "fitz.Annot", title: str, content: str, color) -> None:
    # PyMuPDF stores annotation info as Latin-1/PDFDoc text, so fold Unicode down
    # (em-dash, arrows, Δ, …) to keep popups readable in every PDF viewer.
    annot.set_info(title=_safe(title), content=_safe(content))
    annot.set_colors(stroke=color)
    try:
        annot.set_opacity(0.85)
    except Exception:
        pass
    annot.update()


def annotate_pdf(pdf_bytes: bytes, issues: list[dict]) -> bytes:
    """Return PDF bytes with every failed finding embedded as an in-place note.

    Each finding becomes a real PDF annotation anchored where its offending text
    appears: a coloured highlight + popup comment when the text can be located,
    otherwise a sticky-note comment in the page margin. No extra pages are added —
    only annotations on the original drawing.

    `issues` is a flat list of failed findings, each a dict with (at least):
    page, description, location, severity, check_name.
    """
    # Work on a temp copy of the exact uploaded bytes so we can incrementally
    # save (append only the annotations, leaving the original content verbatim).
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    with open(tmp_path, "wb") as f:
        f.write(pdf_bytes)

    doc = fitz.open(tmp_path)
    page_count = doc.page_count

    # Per-page running offset so unlocated sticky notes stack instead of overlap.
    margin_slots: dict[int, int] = {}

    for n, issue in enumerate(issues, start=1):
        severity = str(issue.get("severity", "ERROR")).upper()
        color = _SEVERITY_COLOR.get(severity, _DEFAULT_COLOR)
        check_name = _clean(issue.get("check_name") or issue.get("category") or "QA")
        description = _clean(issue.get("description"))
        location = issue.get("location") or ""
        pidx = _page_index(issue.get("page"), page_count)
        page = doc[pidx]

        title = f"#{n} · {check_name}"
        content = description or check_name
        if location:
            content = f"{content}\n(Location: {_clean(location)})"

        tokens = _search_tokens(description, location)
        # Title-block fields (Anzahl, Gewicht, Volumen, BETONDECKUNG, …) repeat
        # elsewhere on the sheet; anchor on the bottom-most hit = the title block.
        prefer_bottom = "title block" in location.lower() or "titleblock" in location.lower()
        rect = _find_rect(page, tokens, prefer_bottom=prefer_bottom)

        if rect is not None:
            annot = page.add_highlight_annot(rect)
            _add_comment(annot, title, content, color)
        else:
            slot = margin_slots.get(pidx, 0)
            margin_slots[pidx] = slot + 1
            pt = fitz.Point(page.rect.width - 28, 36 + slot * 26)
            annot = page.add_text_annot(pt, content, icon="Comment")
            _add_comment(annot, title, content, color)

    # Incremental save keeps the user's original bytes intact and only appends
    # the annotations. If that isn't possible (encrypted / oddly structured PDF)
    # fall back to a full rewrite so the download still succeeds.
    saved_incremental = False
    try:
        doc.save(tmp_path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        saved_incremental = True
    except Exception as exc:  # noqa: BLE001 — any save failure → full rewrite
        print(f"[annotate] incremental save failed ({exc}); using full rewrite")

    if saved_incremental:
        doc.close()
        with open(tmp_path, "rb") as f:
            data = f.read()
    else:
        data = doc.tobytes(deflate=True, garbage=3)
        doc.close()

    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    return data
