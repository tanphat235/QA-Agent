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

# Each pattern has ONE capturing group; its matches become candidate anchors.
# Ordered most-specific → most-generic, and that ORDER is what ranks them: a
# schedule row's own values locate the row, whereas the table's name locates
# only the table. Sorting by raw length instead put "Stabliste" ahead of every
# row value, so all sixteen Stabliste findings highlighted the same title word
# and looked like one note.
_TOKEN_PATTERNS = [
    re.compile(r"['‘’]([^'‘’]{2,80})['‘’]"),                       # 'quoted value'
    re.compile(r'["“”]([^"“”]{2,80})["“”]'),                       # "quoted value"
    re.compile(r"(?<![\d.,])(\d{1,4}[.,]\d{2})(?![\d.,])"),        # 3.79, 9.17 — a row's own figures
    re.compile(r"([A-Za-zÄÖÜäöüß][\wÄÖÜäöüß./-]{2,})\s*(?:→|->|:)\s*\w"),  # wrong→correct
    re.compile(r"(\bSchnitt\s+[A-Z]-?[A-Z]?\b)"),                  # Schnitt A-A
    re.compile(r"(\b[A-ZÄÖÜ]{1,3}\d+(?:[/-][A-Z0-9]+)*\b)"),       # XC3, K38/17
    re.compile(r"\bPos\.?\s*0*(\d{1,4})\b", re.IGNORECASE),         # Pos 12
    re.compile(r"(\b[A-ZÄÖÜ]{2,4}\b)"),                            # FV, KTL, V2A
    re.compile(r"(\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]{3,}\b)"),              # Jordahl, Wandansicht
]


def _search_tokens(description: str, location: str) -> list[str]:
    """Ordered, de-duplicated list of strings to look for in the page — most
    specific (longest / most unique) first."""
    desc = description or ""
    raw: list[tuple[int, str]] = []          # (rank, token) — lower rank = more specific
    for label, num in _EBT_RE.findall(desc):
        raw += [(0, f"{label.upper()} {num}"), (0, num)]
    for rank, pat in enumerate(_TOKEN_PATTERNS, start=1):
        raw += [(rank, m) for m in pat.findall(desc)]
    loc = _clean(location)
    last = len(_TOKEN_PATTERNS) + 1
    if loc and len(loc) >= 4:
        # The location names the table or the field, so it is the anchor of last
        # resort — it is the same for every finding in that table.
        raw.append((last, loc))
        # The field name inside a "title block X" / "drawing X" location is the
        # cleanest anchor (e.g. "Anzahl", "Gewicht", "BETONDECKUNG").
        m = re.match(r"(?:title\s*block|drawing)\b[\s/]*(.+)", loc, re.IGNORECASE)
        if m and len(m.group(1)) >= 3:
            raw.append((last, m.group(1)))

    seen: set[str] = set()
    ordered: list[tuple[int, int, str]] = []
    for rank, tok in raw:
        t = _clean(tok)
        if len(t) < 2 or t.lower() in _STOPWORDS or t.lower() in seen:
            continue
        seen.add(t.lower())
        ordered.append((rank, -len(t), t))

    # Pattern order first, longest within a pattern second.
    ordered.sort()
    return [t for _, _, t in ordered]


def _rect_key(rect: "fitz.Rect") -> tuple[int, int, int, int]:
    """Identity of a rectangle, rounded so near-identical hits count as one."""
    return (round(rect.x0), round(rect.y0), round(rect.x1), round(rect.y1))


def _location_region(page: "fitz.Page", location: str) -> "fitz.Rect | None":
    """The part of the page the finding's location names, when it can be found.

    A value like "3.25" occurs all over a drawing, but a finding located in the
    Stabliste belongs in the Stabliste. Anchoring the search under that title
    keeps a schedule finding inside its own table instead of landing on the
    first identical number anywhere on the sheet.
    """
    key = _clean(location).split("/")[0].strip()
    key = re.sub(r"^(?:title\s*block|drawing)\s+", "", key, flags=re.IGNORECASE).strip()
    for candidate in (key, key.split()[0] if key else ""):
        if len(candidate) < 4:
            continue
        try:
            hits = page.search_for(candidate, quads=False)
        except Exception:
            hits = []
        if hits:
            a = hits[0]
            return fitz.Rect(a.x0 - 80, a.y0 - 30, a.x0 + 460, a.y1 + 440)
    return None


def _find_rect(
    page: "fitz.Page",
    tokens: list[str],
    prefer_bottom: bool = False,
    region: "fitz.Rect | None" = None,
) -> "fitz.Rect | None":
    """Where on the page this finding belongs — the first token that matches.

    Two findings are free to resolve to the same rectangle; the caller merges
    them into one note rather than stacking two highlights on the same word.

    prefer_bottom (title-block findings) reads the lowest occurrence first: the
    title block is the bottom-most element, so identical labels in the body and
    the schedules are skipped.
    """
    # Two passes: inside the area the location names first, anywhere second.
    for inside_only in (True, False) if region is not None else (False,):
        for tok in tokens:
            try:
                hits = page.search_for(tok, quads=False)
            except Exception:
                hits = []
            if inside_only and region is not None:
                hits = [r for r in hits if region.contains(r)]
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


def _group_title(group: list[dict]) -> str:
    """Heading for one note: the finding numbers and the check(s) behind them."""
    numbers = ", ".join(f"#{f['n']}" for f in group)
    checks = list(dict.fromkeys(f["check_name"] for f in group))
    if len(group) == 1:
        return f"{numbers} · {checks[0]}"
    what = checks[0] if len(checks) == 1 else f"{len(checks)} checks"
    return f"{numbers} · {what} ({len(group)} findings)"


def _group_content(group: list[dict]) -> str:
    """Body of one note — every finding that belongs to this spot, in order."""
    if len(group) == 1:
        f = group[0]
        body = f["description"] or f["check_name"]
        return f"{body}\n(Location: {f['location']})" if f["location"] else body

    lines = [f"{len(group)} findings at this position:", ""]
    for f in group:
        lines.append(f"#{f['n']} · {f['check_name']}")
        lines.append(f["description"] or "(no description)")
        if f["location"]:
            lines.append(f"(Location: {f['location']})")
        lines.append("")
    return "\n".join(lines).rstrip()


def annotate_pdf(pdf_bytes: bytes, issues: list[dict]) -> bytes:
    """Return PDF bytes with every failed finding embedded as an in-place note.

    Each finding is anchored where its offending text appears: a coloured
    highlight + popup comment when the text can be located, otherwise a
    sticky-note comment in the page margin. No extra pages are added — only
    annotations on the original drawing.

    Findings that land on the SAME piece of text share one note listing all of
    them. Sixteen Stabliste findings anchored on the table's title used to stack
    sixteen highlights on that one word, and the sheet came back looking as if a
    single error had been found — one note reading "5 findings at this position"
    says what is actually there.

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

    # ── Pass 1: resolve every finding to a place ────────────────────────────
    located: dict[tuple, list[dict]] = {}   # (page, rect key) -> findings there
    rects: dict[tuple, "fitz.Rect"] = {}
    unlocated: list[dict] = []

    for n, issue in enumerate(issues, start=1):
        location = _clean(issue.get("location") or "")
        description = _clean(issue.get("description"))
        entry = {
            "n": n,
            "severity": str(issue.get("severity", "ERROR")).upper(),
            "check_name": _clean(issue.get("check_name") or issue.get("category") or "QA"),
            "description": description,
            "location": location,
            "page": _page_index(issue.get("page"), page_count),
        }
        page = doc[entry["page"]]

        tokens = _search_tokens(description, location)
        # Title-block fields (Anzahl, Gewicht, Volumen, BETONDECKUNG, …) repeat
        # elsewhere on the sheet; anchor on the bottom-most hit = the title block.
        prefer_bottom = "title block" in location.lower() or "titleblock" in location.lower()
        region = None if prefer_bottom else _location_region(page, location)
        rect = _find_rect(page, tokens, prefer_bottom=prefer_bottom, region=region)

        if rect is None:
            unlocated.append(entry)
            continue
        key = (entry["page"], _rect_key(rect))
        rects.setdefault(key, rect)
        located.setdefault(key, []).append(entry)

    # ── Pass 2: one note per place, one per unlocated finding ───────────────
    def _colour(group: list[dict]):
        severities = {f["severity"] for f in group}
        worst = "ERROR" if "ERROR" in severities else next(iter(severities), "ERROR")
        return _SEVERITY_COLOR.get(worst, _DEFAULT_COLOR)

    for key, group in located.items():
        pidx, _ = key
        # Keep the page alive: PyMuPDF holds annotations by weak reference to it.
        page = doc[pidx]
        annot = page.add_highlight_annot(rects[key])
        _add_comment(annot, _group_title(group), _group_content(group), _colour(group))

    # Per-page running offset so unlocated sticky notes stack instead of overlap.
    margin_slots: dict[int, int] = {}
    for entry in unlocated:
        pidx = entry["page"]
        page = doc[pidx]
        # Margin fallback — stacked down the right edge and wrapped into further
        # columns so a long finding list cannot run off the sheet.
        slot = margin_slots.get(pidx, 0)
        margin_slots[pidx] = slot + 1
        per_column = max(1, int((page.rect.height - 72) // 26))
        col, row = divmod(slot, per_column)
        pt = fitz.Point(page.rect.width - 28 - col * 30, 36 + row * 26)
        content = _group_content([entry])
        annot = page.add_text_annot(pt, content, icon="Comment")
        _add_comment(annot, _group_title([entry]), content, _colour([entry]))

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
