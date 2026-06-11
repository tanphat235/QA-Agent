"""
Extract structured content from a single-page PDF using pdfplumber.

Uses word-coordinate spatial analysis instead of extract_tables() because
structural drawings use drawn lines for borders rather than proper table structures.
"""
import re
import pdfplumber


def extract_pdf_content(pdf_path: str) -> dict:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
        raw_text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""

        title_block = _extract_title_block(words)
        title_block["max_stabliste_pos"] = _max_pos_in_schedule(words, "Stabliste")
        title_block["max_mattenliste_pos"] = _max_pos_in_schedule(words, "Mattenstahlliste")
        title_block["drawing_title_value"] = _find_text_below_label(words, "Drawing Title")
        title_block["drawing_no_value"] = _find_text_below_label(words, "Drawing No")
        title_block["drawing_name"] = _find_drawing_name(words, page.height)
        title_block["planfreigabe_text"] = _find_planfreigabe_text(raw_text)

        return {
            "raw_text": raw_text,
            "title_block": title_block,
            "formatted": _format_for_llm(raw_text, title_block),
        }


# ── Value to the RIGHT of a label (pos_count circle/square) ─────────────────

_Y_BAND = 14  # pt — spans circle/square annotation padding


def _find_number_right_of_label(words: list[dict], label_fragment: str) -> str | None:
    """Return the nearest integer to the right of the word containing label_fragment."""
    label_word = next(
        (w for w in words if label_fragment.lower() in w["text"].lower()), None
    )
    if label_word is None:
        return None

    label_x1 = label_word["x1"]
    label_y = (label_word["top"] + label_word["bottom"]) / 2

    candidates: list[tuple[float, str]] = [
        (w["x0"], w["text"].strip())
        for w in words
        if w["x0"] > label_x1
        and abs((w["top"] + w["bottom"]) / 2 - label_y) <= _Y_BAND
        and re.fullmatch(r"\d+", w["text"].strip())
    ]
    return min(candidates, key=lambda t: t[0])[1] if candidates else None


# ── Value BELOW a label (Drawing Title, Drawing No.) ────────────────────────

_BELOW_Y_MAX = 70   # pt — max distance below label to search for value
_BELOW_Y_MIN = 2    # pt — skip the label's own bottom edge
_LINE_SNAP   = 4    # pt — words within this y-distance are on the same line


def _find_text_below_label(words: list[dict], label_fragment: str) -> str | None:
    """
    Find text in the box directly below a label (e.g. "Drawing Title:").
    Returns lines of text joined by newline, or None if the box is empty.
    """
    label_word = next(
        (w for w in words if label_fragment.lower() in w["text"].lower()), None
    )
    if label_word is None:
        return None

    label_bottom = label_word["bottom"]
    label_x0 = label_word["x0"]

    # Collect words in the column below the label
    below = sorted(
        [
            w for w in words
            if w["top"] > label_bottom + _BELOW_Y_MIN
            and w["top"] <= label_bottom + _BELOW_Y_MAX
            and w["x0"] >= label_x0 - 8   # slight left tolerance
        ],
        key=lambda w: (w["top"], w["x0"]),
    )

    if not below:
        return None

    # Group into lines and join
    lines: list[str] = []
    current_words: list[str] = []
    current_y: float = below[0]["top"]
    for w in below:
        if abs(w["top"] - current_y) <= _LINE_SNAP:
            current_words.append(w["text"])
        else:
            if current_words:
                lines.append(" ".join(current_words))
            current_words = [w["text"]]
            current_y = w["top"]
    if current_words:
        lines.append(" ".join(current_words))

    result = "\n".join(lines).strip()
    return result or None


# ── Drawing name from top of sheet ──────────────────────────────────────────

def _find_drawing_name(words: list[dict], page_height: float) -> str | None:
    """
    Return the most prominent text cluster in the upper 30% of the drawing sheet
    (excluding the title block area which is at the bottom).
    """
    top_threshold = page_height * 0.30
    top_words = [w for w in words if w["top"] <= top_threshold]
    if not top_words:
        return None
    top_words.sort(key=lambda w: (w["top"], w["x0"]))
    # Return the first non-trivial line of text found
    lines: list[str] = []
    current_words: list[str] = []
    current_y: float = top_words[0]["top"]
    for w in top_words:
        if abs(w["top"] - current_y) <= _LINE_SNAP:
            current_words.append(w["text"])
        else:
            line = " ".join(current_words).strip()
            if len(line) > 5:
                lines.append(line)
            current_words = [w["text"]]
            current_y = w["top"]
    if current_words:
        line = " ".join(current_words).strip()
        if len(line) > 5:
            lines.append(line)
    return lines[0] if lines else None


# ── Title block: pos_count labels ───────────────────────────────────────────

def _extract_title_block(words: list[dict]) -> dict:
    return {
        "letzte_stabstahlposition": _find_number_right_of_label(words, "Stabstahlposition"),
        "letzte_mattenposition":    _find_number_right_of_label(words, "Mattenposition"),
        "revision_title_block":     _find_revision_in_title_block(words),
        "revision_table_last":      _find_last_revision_in_table(words),
        "status_title_block":       _find_status_in_title_block(words),
        # planfreigabe_text is set in extract_pdf_content using raw_text
    }


# ── Schedule max-position: spatial column search ────────────────────────────

_REV_CODE_RE = re.compile(r"[A-Z]{1,2}\d{1,3}", re.IGNORECASE)
_REV_COL_MARGIN = 15  # pt — column width tolerance around "Rev" header

_POS_X_MARGIN = 8  # pt — column width tolerance around "Pos." header


def _max_pos_in_schedule(words: list[dict], schedule_keyword: str) -> str | None:
    schedule_word = next(
        (w for w in words if schedule_keyword.lower() in w["text"].lower()), None
    )
    if schedule_word is None:
        return None

    schedule_top = schedule_word["top"]

    pos_headers = [
        w for w in words
        if re.fullmatch(r"Pos\.?", w["text"].strip(), re.IGNORECASE)
        and w["top"] >= schedule_top - 5
    ]
    if not pos_headers:
        return None

    pos_header = min(pos_headers, key=lambda w: abs(w["top"] - schedule_top))
    col_x0 = pos_header["x0"] - _POS_X_MARGIN
    col_x1 = pos_header["x1"] + _POS_X_MARGIN
    header_bottom = pos_header["bottom"]

    values = [
        int(w["text"].strip())
        for w in words
        if w["top"] >= header_bottom
        and w["x0"] >= col_x0
        and w["x1"] <= col_x1
        and re.fullmatch(r"\d+", w["text"].strip())
        and int(w["text"].strip()) < 100
    ]

    return str(max(values)) if values else None


# ── Status: title block field and Planfreigabe approval text ────────────────

_PLANFREIGABE_Y_BAND = 20  # pt — generous band; Planfreigabe value uses a larger font


def _find_status_in_title_block(words: list[dict]) -> str | None:
    """Return the status code from the cell to the right of the revision code in the title block.

    The 'Status:' label is often rendered in a light colour that pdfplumber may miss,
    so we anchor on the 'Revision:' label (which is reliably extracted) and look for
    a rev-code pattern directly to the right of the revision value in the same row.
    """
    rev_label = next(
        (w for w in words if re.fullmatch(r"Revision:?", w["text"].strip(), re.IGNORECASE)),
        None,
    )
    if rev_label is None:
        print("[drawing_status] Revision label not found — cannot locate status code")
        return None

    # Find the revision code below the label (same column)
    rev_col_x0 = rev_label["x0"] - 8
    rev_col_x1 = rev_label["x1"] + 8
    rev_below = [
        w for w in words
        if w["top"] > rev_label["bottom"] + _BELOW_Y_MIN
        and w["top"] <= rev_label["bottom"] + _BELOW_Y_MAX
        and w["x0"] >= rev_col_x0
        and w["x0"] <= rev_col_x1
        and _REV_CODE_RE.fullmatch(w["text"].strip())
    ]
    if not rev_below:
        print("[drawing_status] Revision code not found below label — cannot anchor status")
        return None

    rev_word = min(rev_below, key=lambda w: w["top"])
    rev_y = (rev_word["top"] + rev_word["bottom"]) / 2
    print(f"[drawing_status] revision anchor: {rev_word['text']!r} at x0={round(rev_word['x0'])} y={round(rev_y)}")

    # Status code is to the right of the revision code on the same row
    status_candidates = [
        w for w in words
        if w["x0"] > rev_word["x1"]
        and abs((w["top"] + w["bottom"]) / 2 - rev_y) <= _Y_BAND
        and _REV_CODE_RE.fullmatch(w["text"].strip())
    ]
    print(f"[drawing_status] status candidates to right of revision: {[(w['text'], round(w['x0'])) for w in status_candidates]}")
    if status_candidates:
        return min(status_candidates, key=lambda w: w["x0"])["text"].strip()
    return None


# Known standard approval phrases — searched in raw text so font/layout don't matter.
_PLANFREIGABE_PHRASES = [
    ("ZUR PRÜFUNG",     "Zur Prüfung"),
    ("ZUR PRUFUNG",     "Zur Prüfung"),       # ASCII fallback for ü
    ("ZUR AUSFÜHRUNG",  "Zur Ausführung Freigegeben"),
    ("ZUR AUSFUHRUNG",  "Zur Ausführung Freigegeben"),  # ASCII fallback
]


def _find_planfreigabe_text(raw_text: str) -> str | None:
    """Return the normalised approval phrase found anywhere in the drawing text."""
    text_upper = raw_text.upper()
    for pattern, canonical in _PLANFREIGABE_PHRASES:
        if pattern in text_upper:
            print(f"[drawing_status] planfreigabe phrase found: {canonical!r}")
            return canonical
    print("[drawing_status] no known planfreigabe phrase found in raw text")
    return None


# ── Revision: title block field and history table ───────────────────────────

def _find_revision_in_title_block(words: list[dict]) -> str | None:
    """Return the revision code in the cell below the 'Revision' label in the title block."""
    label_word = next(
        (w for w in words if re.fullmatch(r"Revision:?", w["text"].strip(), re.IGNORECASE)),
        None,
    )
    if label_word is None:
        return None

    # Constrain x to the Revision cell column so we don't bleed into the Status column.
    col_x0 = label_word["x0"] - 8
    col_x1 = label_word["x1"] + 8

    below = [
        w for w in words
        if w["top"] > label_word["bottom"] + _BELOW_Y_MIN
        and w["top"] <= label_word["bottom"] + _BELOW_Y_MAX
        and w["x0"] >= col_x0
        and w["x0"] <= col_x1
        and _REV_CODE_RE.fullmatch(w["text"].strip())
    ]
    if below:
        return min(below, key=lambda w: w["top"])["text"].strip()

    return None


def _find_last_revision_in_table(words: list[dict]) -> str | None:
    """Return the topmost (most recent) revision code in the revision history table."""
    rev_header = next(
        (w for w in words if re.fullmatch(r"Rev\.?", w["text"].strip(), re.IGNORECASE)),
        None,
    )
    if rev_header is None:
        return None

    col_x0 = rev_header["x0"] - _REV_COL_MARGIN
    col_x1 = rev_header["x1"] + _REV_COL_MARGIN

    entries = [
        w for w in words
        if w["top"] > rev_header["bottom"]
        and w["x0"] >= col_x0
        and w["x1"] <= col_x1
        and _REV_CODE_RE.fullmatch(w["text"].strip())
    ]
    if not entries:
        return None

    return min(entries, key=lambda w: w["top"])["text"].strip()


# ── LLM text formatter ───────────────────────────────────────────────────────

def _format_for_llm(raw_text: str, title_block: dict) -> str:
    parts = ["=== DRAWING TEXT ===", raw_text.strip()]

    # Inject pre-extracted title block values so LLM reads from here, not from raw text
    tb_lines = [
        "\n=== PRE-EXTRACTED TITLE BLOCK VALUES (from coordinate analysis) ===",
        f"Drawing Title: {title_block.get('drawing_title_value') or '(empty)'}",
        f"Drawing No.:   {title_block.get('drawing_no_value') or '(empty)'}",
        f"Drawing Name (top of sheet): {title_block.get('drawing_name') or '(not found)'}",
        f"Revision (title block):      {title_block.get('revision_title_block') or '(empty)'}",
        f"Revision (last in table):    {title_block.get('revision_table_last') or '(not found)'}",
        f"Status (title block):        {title_block.get('status_title_block') or '(empty)'}",
        f"Planfreigabe:                {title_block.get('planfreigabe_text') or '(not found)'}",
    ]
    parts.extend(tb_lines)
    return "\n".join(parts)
