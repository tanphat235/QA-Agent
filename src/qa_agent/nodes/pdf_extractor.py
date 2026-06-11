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
        title_block["gesamtmasse"] = _find_total_mass(raw_text)
        title_block["volumen"] = _find_volumen(words)

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


# ── Exposition class and BETONDECKUNG concrete cover ────────────────────────

# Lookup table: Cmin,dur = Cnom(φ10), ΔCdev = ΔC, Cv = Cnom(φ10) + ΔC
# Source: BẢNG 3.1 – BÊ TÔNG BẢO VỆ (Vietnamese standard)
_EXPOSITION_COVER_TABLE: dict[str, tuple[int, int, int]] = {
    #         (Cmin,dur, ΔCdev, Cv)
    "XC1": (20, 10, 30),
    "XC2": (35, 15, 50),
    "XC3": (35, 15, 50),
    "XC4": (40, 15, 55),
}


def _find_exposition_class(words: list[dict]) -> str | None:
    """Return the exposition class code (XC1–XC4) found anywhere in the drawing."""
    matches = [
        w["text"].strip().upper()
        for w in words
        if re.fullmatch(r"XC[1-4]", w["text"].strip(), re.IGNORECASE)
    ]
    if not matches:
        return None
    codes = set(matches)
    if len(codes) > 1:
        print(f"[exposition_class] multiple XC codes found: {codes} — using first")
    return matches[0]


def _find_betondeckung_values(words: list[dict]) -> dict:
    """Extract Cmin,dur, ΔCdev and Cv from the BETONDECKUNG section.

    Strategy: anchor on the ΔCdev header (most reliably detected via the delta
    character), find the numeric value below it, then scan the same value-row for
    the adjacent numbers — Cmin,dur is the closest number to the LEFT and Cv is
    the closest number to the RIGHT.  This avoids depending on 'Cmin' or 'Cv'
    being a single pdfplumber word (they are often split into 'C'+'min,' and 'C'+'v').
    """
    # ── Step 1: locate ΔCdev header ─────────────────────────────────────────
    dev_h = next(
        (w for w in words
         if "cdev" in w["text"].lower()
         or re.search(r"[△▲Δ∆]", w["text"])),
        None,
    )
    if dev_h is None:
        dev_h = next(
            (w for w in words
             if "dev" in w["text"].lower() and "deckung" not in w["text"].lower()),
            None,
        )
    if dev_h is None:
        print("[exposition_class] ΔCdev header not found — cannot locate BETONDECKUNG values")
        return {"cmin_dur": None, "delta_c": None, "cv": None}

    print(f"[exposition_class] ΔCdev header: {dev_h['text']!r} at x0={round(dev_h['x0'])} top={round(dev_h['top'])}")

    # ── Step 2: find the number directly below the ΔCdev header ─────────────
    dev_below = [
        w for w in words
        if w["top"] > dev_h["bottom"]
        and w["top"] <= dev_h["bottom"] + _BELOW_Y_MAX
        and w["x0"] >= dev_h["x0"] - 15
        and w["x1"] <= dev_h["x1"] + 15
        and re.fullmatch(r"\d+", w["text"].strip())
    ]
    if not dev_below:
        print("[exposition_class] no value found below ΔCdev header")
        return {"cmin_dur": None, "delta_c": None, "cv": None}

    dev_val_word = min(dev_below, key=lambda w: w["top"])
    dev_val      = dev_val_word["text"].strip()
    val_y        = (dev_val_word["top"] + dev_val_word["bottom"]) / 2
    dev_x_center = (dev_val_word["x0"] + dev_val_word["x1"]) / 2

    # ── Step 3: collect all integers in the same row within ±150 pt ──────────
    row_nums = sorted(
        [
            w for w in words
            if re.fullmatch(r"\d+", w["text"].strip())
            and abs((w["top"] + w["bottom"]) / 2 - val_y) <= _Y_BAND
            and abs((w["x0"] + w["x1"]) / 2 - dev_x_center) <= 150
        ],
        key=lambda w: w["x0"],
    )
    print(f"[exposition_class] values row (±150 pt, ±{_Y_BAND} pt y): {[(w['text'], round(w['x0'])) for w in row_nums]}")

    # ── Step 4: assign left → Cmin,dur, center → ΔCdev, right → Cv ──────────
    left  = [w for w in row_nums if w["x0"] < dev_val_word["x0"]]
    right = [w for w in row_nums if w["x0"] > dev_val_word["x1"]]

    cmin_val = left[-1]["text"].strip()  if left  else None  # rightmost of the left group
    cv_val   = right[0]["text"].strip()  if right else None  # leftmost of the right group

    result = {"cmin_dur": cmin_val, "delta_c": dev_val, "cv": cv_val}
    print(f"[exposition_class] values  — cmin_dur={cmin_val!r}  delta_c={dev_val!r}  cv={cv_val!r}")
    return result


# ── Steel content: total mass and element volume ─────────────────────────────

def _find_total_mass(raw_text: str) -> str | None:
    """Return the sum of all Gesamtmasse [kg] values found in the drawing text.

    Uses raw-text regex so font colour or word-split variations don't matter.
    Sums across both Stabliste and Mattenstahlliste if both are present.
    """
    # Matches: "Gesamtmasse [kg] : 392.29"  or  "Gesamtmasse[kg]:392,29"  etc.
    matches = re.findall(
        r"Gesamtmasse\s*\[?kg\]?\s*:?\s*([\d.,]+)",
        raw_text,
        re.IGNORECASE,
    )
    print(f"[steel_content] Gesamtmasse raw_text matches: {matches}")
    if not matches:
        print("[steel_content] Gesamtmasse: no match in raw_text — returning None")
        return None
    total = 0.0
    for m in matches:
        try:
            total += float(m.replace(",", "."))
            print(f"[steel_content] Gesamtmasse: parsed {m!r} → running total={total:.2f}")
        except ValueError as exc:
            print(f"[steel_content] Gesamtmasse: could not parse {m!r}: {exc}")
    return f"{total:.2f}" if total > 0 else None


def _find_volumen(words: list[dict]) -> str | None:
    """Return the volume value from the title block 'Volumen' cell.

    Strategy: find the 'Volumen' label word, then pick the first decimal number
    directly below it.  No x-column constraint is applied because the displayed
    number may be centred differently than the label text.
    """
    label_word = next(
        (w for w in words if "volumen" in w["text"].lower()),
        None,
    )
    if label_word is None:
        print("[steel_content] Volumen: label not found in words")
        return None
    print(f"[steel_content] Volumen label: {label_word['text']!r} at x0={round(label_word['x0'])} bottom={round(label_word['bottom'])}")

    # Collect all decimal numbers below the label within 100 pt (no x constraint)
    below = [
        w for w in words
        if w["top"] > label_word["bottom"] + _BELOW_Y_MIN
        and w["top"] <= label_word["bottom"] + 100
        and re.fullmatch(r"\d+[.,]\d+", w["text"].strip())  # require decimal — avoids stray integers
    ]
    print(f"[steel_content] Volumen below candidates (±100pt, any x): {[(w['text'], round(w['x0']), round(w['top'])) for w in below]}")
    if below:
        result = min(below, key=lambda w: w["top"])["text"].strip()
        print(f"[steel_content] Volumen: picked {result!r}")
        return result
    print("[steel_content] Volumen: no decimal found below label — returning None")
    return None


# ── Title block: pos_count labels ───────────────────────────────────────────

def _extract_title_block(words: list[dict]) -> dict:
    btd = _find_betondeckung_values(words)
    return {
        "letzte_stabstahlposition": _find_number_right_of_label(words, "Stabstahlposition"),
        "letzte_mattenposition":    _find_number_right_of_label(words, "Mattenposition"),
        "revision_title_block":     _find_revision_in_title_block(words),
        "revision_table_last":      _find_last_revision_in_table(words),
        "status_title_block":       _find_status_in_title_block(words),
        "exposition_class":         _find_exposition_class(words),
        "betondeckung_cmin_dur":    btd["cmin_dur"],
        "betondeckung_delta_c":     btd["delta_c"],
        "betondeckung_cv":          btd["cv"],
        # gesamtmasse and volumen are set in extract_pdf_content
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
        f"Exposition class:            {title_block.get('exposition_class') or '(not found)'}",
        f"Betondeckung Cmin,dur:       {title_block.get('betondeckung_cmin_dur') or '(not found)'}",
        f"Betondeckung ΔCdev:          {title_block.get('betondeckung_delta_c') or '(not found)'}",
        f"Betondeckung Cv:             {title_block.get('betondeckung_cv') or '(not found)'}",
        f"Gesamtmasse (total mass):    {title_block.get('gesamtmasse') or '(not found)'} kg",
        f"Volumen (element volume):    {title_block.get('volumen') or '(not found)'} m³",
    ]
    parts.extend(tb_lines)
    return "\n".join(parts)
