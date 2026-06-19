"""
Extract structured content from a single-page PDF using pdfplumber.

Uses word-coordinate spatial analysis instead of extract_tables() because
structural drawings use drawn lines for borders rather than proper table structures.
"""
import re
import pdfplumber


def _char_category(obj: dict) -> str:
    """Classify a char by its transformation matrix.

    normal   — upright text, standard extraction order is correct
    mirrored — reflected (negative determinant); reads backwards and cannot be
               recovered reliably → dropped
    rot180   — rotated 180°; chars extract left-to-right but read right-to-left
    vertical — rotated ±90° (labels on vertical parts); chars extract top-down
               but may read bottom-up depending on rotation direction
    """
    m = obj.get("matrix")
    if not m:
        return "normal"
    a, b, c, d = m[0], m[1], m[2], m[3]
    if a * d - b * c < 0:
        return "mirrored"
    if b == 0 and c == 0:
        return "normal" if a > 0 else "rot180"
    return "vertical"


def _is_normal_char(obj: dict) -> bool:
    if obj.get("object_type") != "char":
        return True
    return _char_category(obj) == "normal"


def _rebuild_rotated_words(chars: list[dict]) -> list[dict]:
    """Rebuild correct reading order for rotated (vertical / 180°) chars.

    pdfplumber orders chars by page position, which reverses the string for
    text rotated 90° CCW or 180° (e.g. vertical EBT label '07162' extracts as
    '26170'). Reading direction is recovered from the matrix advance vector:
    (a,b) points along the baseline — b>0 advances up the page, b<0 down,
    a<0 advances right-to-left.
    Returns word dicts with text/x0/x1/top/bottom compatible with extract_words.
    """
    groups: dict[tuple, list[dict]] = {}
    for ch in chars:
        cat = _char_category(ch)
        if cat in ("normal", "mirrored"):
            continue
        if cat == "vertical":
            b_sign = 1 if ch["matrix"][1] > 0 else -1
            # Tighter x bucket — avoids merging adjacent vertical label columns.
            key = (cat, b_sign, round((ch["x0"] + ch["x1"]) / 2 / 2))
        else:  # rot180 — one row = one group (bucket y-center by 3 pt)
            key = (cat, 0, round((ch["top"] + ch["bottom"]) / 2 / 3))
        groups.setdefault(key, []).append(ch)

    def _flush(out: list[dict], chs: list[dict]) -> None:
        text = "".join(c["text"] for c in chs)
        if not text.strip():
            return
        out.append({
            "text":   text,
            "x0":     min(c["x0"] for c in chs),
            "x1":     max(c["x1"] for c in chs),
            "top":    min(c["top"] for c in chs),
            "bottom": max(c["bottom"] for c in chs),
            "upright": False,
        })

    words: list[dict] = []
    for (cat, b_sign, _), chs in groups.items():
        if cat == "vertical":
            # b>0 (90° CCW): reads bottom-to-top → sort by descending top
            chs.sort(key=lambda c: c["top"], reverse=(b_sign > 0))
            axis = "top"
        else:
            # rot180: reads right-to-left → sort by descending x
            chs.sort(key=lambda c: c["x0"], reverse=True)
            axis = "x0"
        current: list[dict] = []
        for ch in chs:
            if current:
                gap = abs(ch[axis] - current[-1][axis])
                char_size = ch.get("size") or current[-1].get("size") or 8
                if gap > max(char_size * 1.2, 2) or ch["text"].isspace():
                    _flush(words, current)
                    current = []
            if not ch["text"].isspace():
                current.append(ch)
        if current:
            _flush(words, current)
    return words


# Obvious pdfplumber noise from failed vertical-text reconstruction (not real drawing text).
_GARBLED_ROTATED_RE = re.compile(
    r"[@()]{1,}"
    r"|\.\.+"
    r"|[-+]{2,}"
    r"|\b[a-z]{1,2}\d{0,2}\b",  # wi4, nn33, wf3
    re.IGNORECASE,
)


def _is_readable_rotated_label(text: str) -> bool:
    """Keep rotated-text tokens that look like real labels; drop extraction noise."""
    s = text.strip()
    if len(s) < 3:
        return False
    if _GARBLED_ROTATED_RE.search(s):
        # Allow if a clear engineering token is still present (e.g. "2x08151").
        if not re.search(r"\d{4,6}", s) and not re.search(r"[A-ZÄÖÜ][a-zäöüß]{2,}", s):
            return False
    alnum = sum(c.isalnum() or c in "äöüÄÖÜß" for c in s)
    if alnum / len(s) < 0.7:
        return False
    if re.search(r"\d{4,6}", s):
        return True
    if re.search(r"\d+\s*[x×]\s*\d+", s, re.IGNORECASE):
        return True
    if re.search(r"[A-ZÄÖÜ][a-zäöüß]{2,}", s):
        return True
    if re.fullmatch(r"[A-Za-zÄÖÜäöüß0-9\s\-–—.,+/]+", s) and len(s) >= 6:
        return sum(c.isalpha() for c in s) >= 4
    return False


def extract_pdf_content(pdf_path: str) -> dict:
    with pdfplumber.open(pdf_path) as pdf:
        # dedupe_chars removes overprinted duplicate chars (fake-bold rendering
        # that otherwise extracts 'Laubholz' as 'LLaauubbhhoollzz').
        deduped = pdf.pages[0].dedupe_chars(tolerance=1)
        # Rotated text extracts in reversed reading order — pull those chars out
        # of the main flow and re-add them with corrected order; drop mirrored.
        rotated_words = _rebuild_rotated_words(deduped.chars)
        readable_rotated = [w for w in rotated_words if _is_readable_rotated_label(w["text"])]
        dropped_rotated = len(rotated_words) - len(readable_rotated)
        if dropped_rotated:
            print(f"[pdf_extract] dropped {dropped_rotated} garbled rotated/vertical token(s)")
        rotated_words = readable_rotated
        page = deduped.filter(_is_normal_char)
        words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
        raw_text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
        if rotated_words:
            print(f"[pdf_extract] rotated/vertical words (reading-order corrected): "
                  f"{[w['text'] for w in rotated_words][:20]}")
            words.extend(rotated_words)
            raw_text += (
                "\n=== ROTATED / VERTICAL LABELS (reading-order corrected) ===\n"
                + "\n".join(w["text"] for w in rotated_words)
            )

        title_block = _extract_title_block(words, raw_text)
        title_block["max_stabliste_pos"] = _max_pos_in_schedule(words, "Stabliste")
        title_block["max_mattenliste_pos"] = _max_pos_in_schedule(words, "Mattenstahlliste")
        # Use raw-text regex exclusively for these two fields.
        # Word-coordinate approach fails: "Bezeichnung" / "Plan-Nr." are positioned
        # mid-label so the x-constraint collects neighbouring Revision/Status values
        # instead of the actual drawing title / drawing number.
        title_block["drawing_title_value"] = _find_drawing_title_raw(raw_text)
        title_block["drawing_no_value"]    = _find_drawing_no_raw(raw_text)
        title_block["drawing_name"] = _find_drawing_name(words, page.height)
        title_block["planfreigabe_text"] = _find_planfreigabe_text(raw_text)
        title_block["gesamtmasse"] = _find_total_mass(raw_text)
        title_block["volumen"]     = _find_volumen(words, raw_text)
        title_block["gewicht"]     = _find_gewicht(words, raw_text)
        title_block["anzahl"]      = _find_anzahl(words, raw_text)
        _rd_found, _rd_max_qty = _find_rd_ebt_data(raw_text)
        title_block["rd_ebt_table_found"] = _rd_found
        title_block["rd_ebt_max_qty"] = _rd_max_qty
        # Match just the stem "lastausgleich" — covers both spellings
        # (Lastausgleichgehänge / Lastausgleichsgehänge) and tolerates pdfplumber
        # encoding variations for the umlaut ä.
        _la_match = re.search(r"lastausgleich", raw_text, re.IGNORECASE)
        _la_matched_txt = _la_match.group(0) if _la_match else None
        title_block["lastausgleich_present"] = bool(_la_match)
        print(f"[lastausgleich] text_present={bool(_la_match)}  matched={_la_matched_txt!r}")

        stabliste_total         = _find_stabliste_total(raw_text)
        mattenstahlliste_total  = _find_mattenstahlliste_total(raw_text)
        einbauteilliste_items   = _merge_einbauteilliste_items(
            _find_einbauteilliste_table(words),
            _find_einbauteilliste_items(raw_text),
        )
        print(f"[steel_list_check] drawing: stab={stabliste_total!r}  matt={mattenstahlliste_total!r}  ebt_count={len(einbauteilliste_items)}")
        return {
            "raw_text":              raw_text,
            "title_block":           title_block,
            "formatted":             _format_for_llm(raw_text, title_block),
            "stabliste_total":       stabliste_total,
            "mattenstahlliste_total": mattenstahlliste_total,
            "einbauteilliste_items": einbauteilliste_items,
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

_XC_CODE_RE = re.compile(r"XC\s*[-]?\s*([1-4])", re.IGNORECASE)
_INT_WORD_RE = re.compile(r"^\d+$")


def _normalize_xc_code(text: str) -> str | None:
    m = _XC_CODE_RE.search(text)
    if not m:
        return None
    return f"XC{m.group(1)}"


def _betondeckung_scope(words: list[dict]) -> list[dict]:
    """Limit search to the title-block BETONDECKUNG table area."""
    anchors = [
        w for w in words
        if "betondeckung" in w["text"].lower()
        or re.search(r"beton\s*deckung", w["text"], re.IGNORECASE)
    ]
    if not anchors:
        # Title block is bottom of sheet — use lower 35% as fallback window.
        if not words:
            return words
        max_top = max(w["top"] for w in words)
        cutoff = max_top * 0.65
        return [w for w in words if w["top"] >= cutoff]

    anchor = max(anchors, key=lambda w: w["top"])
    y0 = anchor["top"] - 8
    y1 = anchor["bottom"] + 90
    return [w for w in words if y0 <= w["top"] <= y1]


def _find_numeric_near_label(
    words: list[dict],
    label_fragments: list[str],
    *,
    prefer_bottommost: bool = True,
    same_row_y: float = 18,
    below_y_max: float = 55,
    right_x_max: float = 110,
    column_x_slack: float = 28,
) -> str | None:
    """Return an integer value to the right of a label, or directly below it."""
    label_word = None
    matched_frag = ""
    for frag in label_fragments:
        hits = [w for w in words if frag.lower() in w["text"].lower()]
        if hits:
            label_word = max(hits, key=lambda w: w["top"]) if prefer_bottommost else hits[0]
            matched_frag = frag
            break
    if label_word is None:
        return None

    label_y = (label_word["top"] + label_word["bottom"]) / 2
    label_x0 = label_word["x0"]
    label_x1 = label_word["x1"]

    right = sorted(
        [
            w for w in words
            if _INT_WORD_RE.fullmatch(w["text"].strip())
            and w["x0"] >= label_x1 - 4
            and w["x0"] <= label_x1 + right_x_max
            and abs((w["top"] + w["bottom"]) / 2 - label_y) <= same_row_y
        ],
        key=lambda w: w["x0"],
    )
    if right:
        val = right[0]["text"].strip()
        print(f"[near_label] '{matched_frag}' right → {val!r}")
        return val

    below = sorted(
        [
            w for w in words
            if _INT_WORD_RE.fullmatch(w["text"].strip())
            and w["top"] > label_word["bottom"] + _BELOW_Y_MIN
            and w["top"] <= label_word["bottom"] + below_y_max
            and w["x0"] >= label_x0 - column_x_slack
            and w["x0"] <= label_x1 + column_x_slack
        ],
        key=lambda w: w["top"],
    )
    if below:
        val = below[0]["text"].strip()
        print(f"[near_label] '{matched_frag}' below → {val!r}")
        return val
    return None


def _find_xc_split_adjacent(words: list[dict]) -> str | None:
    """Handle 'XC' and '3' extracted as separate words on the same row."""
    xc_words = [w for w in words if re.fullmatch(r"XC", w["text"].strip(), re.IGNORECASE)]
    if not xc_words:
        return None
    for xc in sorted(xc_words, key=lambda w: w["top"], reverse=True):
        y = (xc["top"] + xc["bottom"]) / 2
        for w in words:
            if not re.fullmatch(r"[1-4]", w["text"].strip()):
                continue
            if w["x0"] > xc["x1"] - 2 and w["x0"] < xc["x1"] + 35:
                if abs((w["top"] + w["bottom"]) / 2 - y) <= 16:
                    code = f"XC{w['text'].strip()}"
                    print(f"[exposition_class] split adjacent words → {code!r}")
                    return code
    return None


def _find_xc_near_exposition_label(words: list[dict], raw_text: str) -> str | None:
    """Find XC code beside or below Expositionsklasse / Korrosionsklasse labels."""
    label_frags = [
        "expositionsklasse", "exposition class", "exposition",
        "korrosionsklasse", "korrosion", "expos.klasse", "expos",
    ]
    for frag in label_frags:
        hits = [w for w in words if frag.lower() in w["text"].lower()]
        if not hits:
            continue
        label_word = max(hits, key=lambda w: w["top"])
        label_y = (label_word["top"] + label_word["bottom"]) / 2

        for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
            code = _normalize_xc_code(w["text"])
            if not code:
                continue
            wy = (w["top"] + w["bottom"]) / 2
            if w["x0"] >= label_word["x1"] - 6 and abs(wy - label_y) <= 20:
                print(f"[exposition_class] label '{frag}' right → {code!r}")
                return code
            if (
                w["top"] > label_word["bottom"] + _BELOW_Y_MIN
                and w["top"] <= label_word["bottom"] + _BELOW_Y_MAX
                and w["x0"] >= label_word["x0"] - 25
            ):
                print(f"[exposition_class] label '{frag}' below → {code!r}")
                return code

    for frag in ("Expositionsklasse", "Exposition", "Korrosionsklasse", "Korrosion"):
        m = re.search(rf"{frag}[^\n]{{0,60}}(XC\s*[-]?\s*[1-4])", raw_text, re.IGNORECASE)
        if m:
            code = _normalize_xc_code(m.group(1))
            if code:
                print(f"[exposition_class] raw same-line '{frag}' → {code!r}")
                return code
        m = re.search(rf"{frag}[^\n]*\n\s*(XC\s*[-]?\s*[1-4])", raw_text, re.IGNORECASE)
        if m:
            code = _normalize_xc_code(m.group(1))
            if code:
                print(f"[exposition_class] raw next-line '{frag}' → {code!r}")
                return code
    return None


def _find_exposition_class(words: list[dict], raw_text: str = "") -> str | None:
    """Return exposition class XC1–XC4 from label proximity or text patterns."""
    near_label = _find_xc_near_exposition_label(words, raw_text)
    if near_label:
        return near_label

    split = _find_xc_split_adjacent(words)
    if split:
        return split

    xc_words = [w for w in words if _normalize_xc_code(w["text"])]
    if xc_words:
        code = _normalize_xc_code(max(xc_words, key=lambda w: w["top"])["text"])
        if code:
            print(f"[exposition_class] standalone word (title block) → {code!r}")
            return code

    m = re.search(r"\b(XC\s*[-]?\s*[1-4])\b", raw_text, re.IGNORECASE)
    if m:
        code = _normalize_xc_code(m.group(1))
        if code:
            print(f"[exposition_class] raw text pattern → {code!r}")
            return code

    print("[exposition_class] XC code not found")
    return None


def _find_betondeckung_by_delta_anchor(words: list[dict]) -> dict:
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
         if re.search(r"c\s*dev", w["text"], re.IGNORECASE)
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
        print("[exposition_class] ΔCdev header not found — anchor strategy skipped")
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
        label_y = (dev_h["top"] + dev_h["bottom"]) / 2
        dev_right_words = sorted(
            [
                w for w in words
                if _INT_WORD_RE.fullmatch(w["text"].strip())
                and w["x0"] >= dev_h["x1"] - 4
                and w["x0"] <= dev_h["x1"] + 60
                and abs((w["top"] + w["bottom"]) / 2 - label_y) <= 18
            ],
            key=lambda w: w["x0"],
        )
        if dev_right_words:
            dev_val_word = dev_right_words[0]
        else:
            print("[exposition_class] no value found below/right of ΔCdev header")
            return {"cmin_dur": None, "delta_c": None, "cv": None}
    else:
        dev_val_word = min(dev_below, key=lambda w: w["top"])

    dev_val = dev_val_word["text"].strip()
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
    print(f"[exposition_class] anchor values — cmin_dur={cmin_val!r}  delta_c={dev_val!r}  cv={cv_val!r}")
    return result


def _find_betondeckung_from_raw(raw_text: str) -> dict:
    """Regex fallback for BETONDECKUNG values on same line or next line."""
    result: dict[str, str | None] = {"cmin_dur": None, "delta_c": None, "cv": None}
    if not re.search(r"beton\s*deckung|betondeckung", raw_text, re.IGNORECASE):
        return result

    patterns = [
        (r"cmin\s*,?\s*dur[^\d\n]{0,20}(\d+)", "cmin_dur"),
        (r"(?:[△▲Δ∆]\s*c\s*dev|delta\s*c\s*dev|cdev)[^\d\n]{0,20}(\d+)", "delta_c"),
        (r"(?<![a-z])cv[^\d\n]{0,15}(\d+)", "cv"),
        (r"cmin\s*,?\s*dur[^\n]*\n\s*(\d+)", "cmin_dur"),
        (r"(?:[△▲Δ∆]\s*c\s*dev|delta\s*c\s*dev|cdev)[^\n]*\n\s*(\d+)", "delta_c"),
        (r"(?<![a-z])cv[^\n]*\n\s*(\d+)", "cv"),
    ]
    for pat, key in patterns:
        if result[key]:
            continue
        m = re.search(pat, raw_text, re.IGNORECASE)
        if m:
            result[key] = m.group(1)
            print(f"[exposition_class] raw '{key}' → {result[key]!r}")

    if not all(result.values()):
        block = re.search(
            r"beton\s*deckung.*?(?:\n.*?){0,8}(\d+)\s+(\d+)\s+(\d+)",
            raw_text, re.IGNORECASE | re.DOTALL,
        )
        if block:
            triple = (block.group(1), block.group(2), block.group(3))
            result["cmin_dur"] = result["cmin_dur"] or triple[0]
            result["delta_c"] = result["delta_c"] or triple[1]
            result["cv"] = result["cv"] or triple[2]
            print(f"[exposition_class] raw triple row → {triple}")
    return result


def _find_betondeckung_values(words: list[dict], raw_text: str = "") -> dict:
    """Extract Cmin,dur, ΔCdev and Cv — value to the right of or below each header."""
    scoped = _betondeckung_scope(words)

    by_label = {
        "cmin_dur": _find_numeric_near_label(
            scoped, ["cmin,dur", "cmindur", "cmin,", "cmin", "min,dur"],
        ),
        "delta_c": _find_numeric_near_label(
            scoped, ["cdev", "δc", "Δc", "∆c", "dcdev", "delta"],
        ),
        "cv": _find_numeric_near_label(scoped, ["cv", "c v"]),
    }
    anchor = _find_betondeckung_by_delta_anchor(scoped)
    raw_vals = _find_betondeckung_from_raw(raw_text)

    merged = {
        "cmin_dur": by_label["cmin_dur"] or anchor["cmin_dur"] or raw_vals["cmin_dur"],
        "delta_c":  by_label["delta_c"]  or anchor["delta_c"]  or raw_vals["delta_c"],
        "cv":       by_label["cv"]       or anchor["cv"]       or raw_vals["cv"],
    }
    print(
        f"[exposition_class] merged — cmin_dur={merged['cmin_dur']!r}  "
        f"delta_c={merged['delta_c']!r}  cv={merged['cv']!r}"
    )
    return merged


# ── Lastausgleichgehänge: RD-type EBT quantities in Einbauteilliste ──────────

def _find_rd_ebt_data(raw_text: str) -> tuple[bool, int]:
    """Return (einbauteilliste_found, max_menge_of_RD_type_EBTs).

    Detection uses multiple fallback markers so that bold-font extraction
    failures for the compound title word don't cause false NOT FOUND.
    RD-type rows are scanned across the full raw_text (the EBT table is the
    only place in a structural drawing where RD\\d+ product codes appear).
    """
    # ── Step 1: detect Einbauteilliste via any identifiable marker ────────────
    _MARKERS = [
        (r"einbauteilliste", "full title"),
        (r"einbauteil",      "title prefix (split word)"),
        (r"\bEBT\b",         "EBT column header"),
        (r"EBT.{0,10}Nummer","EBT-Nummer header"),
    ]
    detected_by = None
    for pattern, label in _MARKERS:
        if re.search(pattern, raw_text, re.IGNORECASE):
            detected_by = label
            break

    if detected_by is None:
        print("[lastausgleich] Einbauteilliste: no marker found in raw_text")
        # Print first 800 chars of raw_text so we can inspect what pdfplumber gave us
        preview = raw_text[:800].replace("\n", "↵")
        print(f"[lastausgleich] raw_text (first 800 chars):\n{preview}")
        return (False, 0)

    print(f"[lastausgleich] Einbauteilliste detected via: {detected_by!r} ✓")

    # ── Step 2: scan ALL lines for RD\d+ codes ───────────────────────────────
    # \b\d+\b = standalone integer (word-boundary on both sides):
    #   "RD42"  → no \b before '4' (D is also a word char) → "42" NOT matched
    #   "385mm" → no \b after  '5' (m is also a word char) → "385" NOT matched
    #   " 4 "   → \b on both sides → "4" IS matched
    # So the last element of standalone_nums is always the Menge.
    max_qty = 0
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not re.search(r"RD\d+", stripped, re.IGNORECASE):
            continue
        standalone_nums = re.findall(r"\b\d+\b", stripped)
        print(f"[lastausgleich]   RD line  : {stripped!r}")
        print(f"[lastausgleich]   numbers  : {standalone_nums}  → Menge={standalone_nums[-1] if standalone_nums else 'none'}")
        if standalone_nums:
            max_qty = max(max_qty, int(standalone_nums[-1]))

    print(f"[lastausgleich] max RD-type Menge={max_qty}")
    return (True, max_qty)


# ── Steel content: total mass and element volume ─────────────────────────────

def _find_total_mass(raw_text: str) -> str | None:
    """Return the sum of all Gesamtmasse [kg] values found in the drawing text.

    Uses raw-text regex so font colour or word-split variations don't matter.
    Sums across both Stabliste and Mattenstahlliste if both are present.
    Falls back to the section-aware Stabliste search when no direct label matches.
    """
    # Matches: "Gesamtmasse [kg] : 392.29", "Gesamtmasse[kg]:392,29",
    # and the bilingual "Gesamtmasse/ Total mass [kg] : 442.15".
    matches = re.findall(
        r"Gesamtmasse\s*(?:/\s*Total\s+mass\s*)?\[?\s*kg\s*\]?\s*:?\s*([\d.,]+)",
        raw_text,
        re.IGNORECASE,
    )
    print(f"[steel_content] Gesamtmasse raw_text matches: {matches}")
    if matches:
        total = 0.0
        for m in matches:
            try:
                total += float(m.replace(",", "."))
                print(f"[steel_content] Gesamtmasse: parsed {m!r} → running total={total:.2f}")
            except ValueError as exc:
                print(f"[steel_content] Gesamtmasse: could not parse {m!r}: {exc}")
        if total > 0:
            return f"{total:.2f}"
    # Fallback: locate the Stabliste table and take its closing total
    val = _find_stabliste_total(raw_text)
    print(f"[steel_content] Gesamtmasse fallback via Stabliste section: {val!r}")
    return val


def _find_drawing_title_raw(raw_text: str) -> str | None:
    """Extract drawing title from raw text.

    Looks for the text on the line(s) immediately after the
    'Bezeichnung' or 'Drawing Title' label.  Returns up to two lines joined
    with a space so callers can search the full bilingual title string.
    """
    for label_pat in (
        r"Bezeichnung[^:\n]*:\s*\n\s*(.+)",    # German label + next line
        r"Drawing Title[^:\n]*:\s*\n\s*(.+)",   # English label + next line
        r"Bezeichnung[^:\n]*:\s*([^\n:]{5,})",  # same-line value
    ):
        m = re.search(label_pat, raw_text, re.IGNORECASE)
        if m:
            rest = m.group(1).strip()
            lines = [l.strip() for l in rest.split("\n") if l.strip() and len(l.strip()) > 3]
            result = " ".join(lines[:2]) if lines else rest
            print(f"[drawing_title_raw] found: {result[:80]!r}")
            return result or None
    print("[drawing_title_raw] no match in raw_text")
    return None


def _find_drawing_no_raw(raw_text: str) -> str | None:
    """Extract drawing number from raw text.

    Tries three strategies in order:
    1. Value on the line AFTER a 'Drawing No' or 'Plan-Nr' label
    2. Value on the SAME line after the label
    3. First occurrence of the project drawing-number format anywhere
       (≥5 dash-separated alphanumeric segments, e.g. FRA31-LUP-ZZ-03-DR-S-8850)
    """
    # Strategy 1: next-line value
    m = re.search(
        r"(?:Drawing No|Plan-Nr)[^\n]*\n\s*([A-Z]{2,}[A-Z0-9]*(?:-[A-Z0-9]+){4,})",
        raw_text, re.IGNORECASE,
    )
    if m:
        val = m.group(1).split()[0].strip().upper()   # take just the first token
        print(f"[drawing_no_raw] found (next-line): {val!r}")
        return val
    # Strategy 2: same-line value (label and number on one line after ":")
    m = re.search(
        r"(?:Drawing No|Plan-Nr)[^:\n]*:\s*([A-Z]{2,}[A-Z0-9]*(?:-[A-Z0-9]+){4,})",
        raw_text, re.IGNORECASE,
    )
    if m:
        val = m.group(1).split()[0].strip().upper()
        print(f"[drawing_no_raw] found (same-line): {val!r}")
        return val
    # Strategy 3: any drawing-number-like string (≥6 dash-separated segments)
    m = re.search(r"\b([A-Z]{2,}[0-9]+(?:-[A-Z0-9]+){5,})\b", raw_text)
    if m:
        val = m.group(1).strip().upper()
        print(f"[drawing_no_raw] found (pattern): {val!r}")
        return val
    print("[drawing_no_raw] no match in raw_text")
    return None


def _find_numeric_right_of(words: list[dict], label_fragment: str) -> str | None:
    """Find the first numeric value to the RIGHT of the title-block label word.

    The title block is always at the BOTTOM of the drawing, so we take the
    LAST (bottommost / highest `top` coordinate) occurrence of the label to
    avoid matching identically-named columns in rebar or position tables
    higher on the page.  A ±15 pt vertical tolerance handles cell centering.
    """
    matches = [w for w in words if label_fragment.lower() in w["text"].lower()]
    if not matches:
        print(f"[right_of_label] '{label_fragment}' not found in words")
        return None
    # Title block = bottommost label on the page
    label_word = max(matches, key=lambda w: w["top"])
    candidates = sorted(
        [
            w for w in words
            if abs(w["top"] - label_word["top"]) <= 15   # same row ±15 pt
            and w["x0"] > label_word["x1"]               # strictly to the right
            and re.search(r"\d", w["text"])               # contains at least one digit
        ],
        key=lambda w: w["x0"],
    )
    if candidates:
        val = candidates[0]["text"].strip().replace(",", ".")
        print(f"[right_of_label] '{label_fragment}' (bottom occ. top={round(label_word['top'])}) → {val!r}")
        return val
    print(f"[right_of_label] '{label_fragment}': no numeric word to the right (±15 pt)")
    return None


def _find_bilingual_value(raw_text: str, german: str, english: str, integer_only: bool = False) -> str | None:
    """Extract the numeric value from a bilingual title-block label.

    Recognises two pdfplumber raw-text layouts:
      Same-line  : 'Volumen / Volume: 4 m³ Gewicht / Weight: …'
      Split-line : 'Volumen / Volume: Gewicht / Weight:\\n4 m³ 10 to'

    Requiring BOTH the German and English words makes the pattern specific to the
    title block and avoids false matches on 'Anzahl:' columns in rebar tables.
    """
    num_pat = r"\d+" if integer_only else r"[\d.,]+"
    # Dump the raw-text context around the German label for diagnostics
    ctx = re.search(rf".{{0,10}}{german}.{{0,80}}", raw_text, re.IGNORECASE)
    print(f"[bilingual_raw] '{german}' context: {ctx.group()!r}" if ctx else f"[bilingual_raw] '{german}' not found in raw_text")

    # Same-line: 'German / English: <value>'
    m = re.search(
        rf"{german}[^:\n]*/[^:\n]*{english}[^:\n]*:\s*({num_pat})",
        raw_text, re.IGNORECASE,
    )
    if m:
        val = m.group(1).replace(",", ".")
        print(f"[bilingual_raw] '{german}/{english}' same-line → {val!r}")
        return val
    # Split-line: 'German / English: <other label>\n<value>'
    m = re.search(
        rf"{german}[^:\n]*/[^:\n]*{english}[^:\n]*:[^\d\n]*\n\s*({num_pat})",
        raw_text, re.IGNORECASE,
    )
    if m:
        val = m.group(1).replace(",", ".")
        print(f"[bilingual_raw] '{german}/{english}' next-line → {val!r}")
        return val
    # Last resort: just find the first number after the German label anywhere on its line
    m = re.search(rf"{german}[^\n]*?({num_pat})", raw_text, re.IGNORECASE)
    if m:
        val = m.group(1).replace(",", ".")
        print(f"[bilingual_raw] '{german}' inline search → {val!r}")
        return val
    print(f"[bilingual_raw] '{german}/{english}': no match")
    return None


# Units that may sit next to (or be merged with) a title-block value — stripped
# so only the number is kept. Critical: this lets us REJECT a bare unit word like
# "m3" / "to" that would otherwise be mistaken for the value.
_TB_UNIT_RE = r"(?:m³|m3|m²|m2|to|t|kg|stk|stück|pcs)"


def _tb_numeric(text: str, integer_only: bool = False) -> str | None:
    """Return the numeric part of a title-block cell, or None if it is not a value.

    Accepts "3.21", "3,21", "3.21m³", "8.03 to", "1" — rejects bare units ("m3",
    "to", "T") and codes ("WE104"). Decimal comma is normalised to a dot.
    """
    t = re.sub(r"\s+", "", text or "")
    num = r"\d+" if integer_only else r"\d+(?:[.,]\d+)?"
    m = re.fullmatch(rf"({num}){_TB_UNIT_RE}?", t, re.IGNORECASE)
    return m.group(1).replace(",", ".") if m else None


def _next_label_x(words: list[dict], anchor: dict) -> float | None:
    """x0 of the next column's label to the right of `anchor` on the same row.

    The title block lays out cells side by side (Volumen | Gewicht | Anzahl | …).
    The value for one label must never be read past the NEXT label — that belongs
    to the next column. A "label" is an alphabetic word of ≥4 letters (real column
    headers), so short unit tokens ("m³", "to", "T", "kg") are not treated as the
    boundary.
    """
    def _overlaps(w: dict) -> bool:
        return min(w["bottom"], anchor["bottom"]) - max(w["top"], anchor["top"]) > 0

    xs = [
        w["x0"] for w in words
        if w["x0"] > anchor["x1"] + 2 and _overlaps(w)
        and sum(c.isalpha() for c in w["text"]) >= 4
    ]
    return min(xs, default=None)


def _value_near_word(
    words: list[dict], anchor: dict, integer_only: bool = False,
    right_bound: float | None = None,
) -> str | None:
    """Find the numeric value belonging to a label word.

    The value is the nearest PURE number that lies in the label's own COLUMN
    (between the label's left edge and `right_bound` = the next column's label) and
    on the label's row OR below it. This covers all title-block layouts: value to
    the right on the same row, value on the row directly below, or value in a
    compact cell whose row nearly touches the label. Adjacent unit tokens ("m3",
    "to", "T") and codes are rejected, and the search never crosses into the next
    column, so a neighbour's value can never be picked.
    """
    hi = right_bound if right_bound is not None else anchor["x1"] + 140
    lo = anchor["x0"] - 25
    acx = (anchor["x0"] + anchor["x1"]) / 2

    candidates: list[tuple[dict, str]] = []
    for w in words:
        cx = (w["x0"] + w["x1"]) / 2
        if not (lo <= cx < hi):                       # must be in this column
            continue
        if w["top"] < anchor["top"] - 3:              # not on a row above the label
            continue
        if w["top"] > anchor["bottom"] + 55:          # not too far below
            continue
        v = _tb_numeric(w["text"], integer_only)
        if v is not None:
            candidates.append((w, v))
    if not candidates:
        return None
    # Nearest first: topmost row (same row before the row below), then the token
    # whose centre best lines up under the label.
    candidates.sort(key=lambda t: (t[0]["top"], abs((t[0]["x0"] + t[0]["x1"]) / 2 - acx)))
    return candidates[0][1]


def _find_titleblock_value(
    words: list[dict], label_fragment: str, integer_only: bool = False,
) -> str | None:
    """Value for a title-block label, regardless of whether it is printed to the
    right of the label or on the row below it. Uses the bottommost occurrence of
    the label (the title block sits at the bottom of the sheet) and never reads
    past the next column's label."""
    matches = [w for w in words if label_fragment.lower() in w["text"].lower()]
    if not matches:
        return None
    label = max(matches, key=lambda w: w["top"])
    val = _value_near_word(words, label, integer_only, _next_label_x(words, label))
    print(f"[titleblock] '{label_fragment}' (top={round(label['top'])}) → {val!r}")
    return val


def _find_volumen(words: list[dict], raw_text: str) -> str | None:
    return _find_titleblock_value(words, "Volumen") or _find_bilingual_value(raw_text, "Volumen", "Volume")


def _find_gewicht(words: list[dict], raw_text: str) -> str | None:
    """Gewicht / Weight — preferably anchored to the same row as 'Volumen' so we
    don't pick up a steel-list 'Gewicht' column header higher on the sheet.
    The value may be to the right of the label OR on the row below it.
    """
    vol_matches = [w for w in words if "volumen" in w["text"].lower()]
    if vol_matches:
        vol_word = max(vol_matches, key=lambda w: w["top"])   # bottommost = title block
        vol_y = vol_word["top"]
        gwt_matches = [
            w for w in words
            if "gewicht" in w["text"].lower() and abs(w["top"] - vol_y) <= 8
        ]
        if gwt_matches:
            gwt_word = max(gwt_matches, key=lambda w: w["x0"])  # rightmost if multiple
            val = _value_near_word(words, gwt_word, right_bound=_next_label_x(words, gwt_word))
            if val is not None:
                print(f"[gewicht] near Gewicht on Volumen row (y≈{round(vol_y)}) → {val!r}")
                return val
            print("[gewicht] Gewicht found on vol-row but no numeric value right/below")
        else:
            print(f"[gewicht] no 'Gewicht' word on Volumen row (y≈{round(vol_y)} ±8pt)")
    # Fallbacks: bottommost 'Gewicht' anywhere, then bilingual raw-text search.
    return _find_titleblock_value(words, "Gewicht") or _find_bilingual_value(raw_text, "Gewicht", "Weight")


def _find_anzahl(words: list[dict], raw_text: str) -> str | None:
    val = (
        _find_titleblock_value(words, "Anzahl", integer_only=True)
        or _find_bilingual_value(raw_text, "Anzahl", "Quantity", integer_only=True)
    )
    if val:
        m = re.match(r"(\d+)", val)
        return m.group(1) if m else val
    return None



# ── Title block: pos_count labels ───────────────────────────────────────────

def _extract_title_block(words: list[dict], raw_text: str = "") -> dict:
    btd = _find_betondeckung_values(words, raw_text)
    return {
        "letzte_stabstahlposition": _find_number_right_of_label(words, "Stabstahlposition"),
        "letzte_mattenposition":    _find_number_right_of_label(words, "Mattenposition"),
        "revision_title_block":     _find_revision_in_title_block(words),
        "revision_table_last":      _find_last_revision_in_table(words),
        "status_title_block":       _find_status_in_title_block(words),
        "exposition_class":         _find_exposition_class(words, raw_text),
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


# ── Steel list cross-check extractors ────────────────────────────────────────

def _find_stabliste_total(raw_text: str) -> str | None:
    """Gesamtgewicht/Gesamtmasse from the Stabliste section.

    Drawing PDF: bilingual 'Gesamtmasse / Total mass [kg]: value' label.
    Steel list PDF: 'Gesamtgewicht value' inside a 'Stabliste - Biegeformen' section.
    Always takes the LAST occurrence — the final total, not per-page subtotals.

    The loose 'Gesamtmasse ...' fallback is intentionally absent: the steel list PDF
    prints an intermediate per-page subtotal also labelled 'Gesamtmasse' which would
    be matched instead of the correct final 'Gesamtgewicht' on the last page.
    """
    # Strategy 1 — drawing PDF only: very specific bilingual label with English counterpart
    matches = re.findall(
        r"Gesamtmasse[^:\n]*/?\s*Total\s+mass[^:\n]*:?\s*([\d.,]+)",
        raw_text, re.IGNORECASE,
    )
    if matches:
        val = matches[-1].replace(",", ".")
        print(f"[steel_list_check] Stabliste Gesamtmasse (drawing bilingual): {val!r}")
        return val

    # Strategy 2 — steel list PDF: find 'Stabliste' section header, take LAST Gesamtgewicht
    # Page order in steel list: Mattenstahlliste → Stabliste → Einbauteilliste
    stab_m = re.search(r"\bStabliste\b", raw_text, re.IGNORECASE)
    if stab_m:
        # Clip at next major section following Stabliste
        next_m = re.search(
            r"\b(?:Mattenstahlliste|Einbauteilliste)\b",
            raw_text[stab_m.end():], re.IGNORECASE,
        )
        end = stab_m.end() + (next_m.start() if next_m else len(raw_text))
        section = raw_text[stab_m.start():end]
        print(f"[steel_list_check] Stabliste section: {len(section)} chars, "
              f"clipped_at={next_m.group(0) if next_m else 'EOF'}")
        gw = re.findall(r"Gesamtgewicht\s*:?\s*([\d.,]+)", section, re.IGNORECASE)
        print(f"[steel_list_check] Stabliste Gesamtgewicht candidates: {gw}")
        if gw:
            val = gw[-1].replace(",", ".")
            print(f"[steel_list_check] Stabliste Gesamtgewicht (last in section): {val!r}")
            return val

    print("[steel_list_check] Stabliste total: not found")
    return None


def _find_mattenstahlliste_total(raw_text: str) -> str | None:
    """Gesamtgewicht from the Mattenstahlliste section.

    Drawing PDF uses bilingual 'Gesamtgewicht / Total weight [kg]' label.
    Steel list PDF uses 'Gesamtgewicht' inside a 'Mattenstahlliste' section header.
    Always takes the LAST occurrence to skip intermediate per-storey subtotals.
    """
    # Drawing PDF style: bilingual label with English part — very specific
    matches = re.findall(
        r"Gesamtgewicht[^:\n]*/?\s*Total\s+weight[^:\n]*:?\s*([\d.,]+)",
        raw_text, re.IGNORECASE,
    )
    if matches:
        val = matches[-1].replace(",", ".")
        print(f"[steel_list_check] Mattenstahlliste Gesamtgewicht (drawing): {val!r}")
        return val

    # Strategy 2 — steel list PDF: find 'Mattenstahlliste' section header, take LAST Gesamtgewicht.
    # Page order in steel list: Mattenstahlliste → Stabliste → Einbauteilliste,
    # so clip at the next 'Stabliste' section that follows it.
    matt_m = re.search(r"\bMattenstahlliste\b", raw_text, re.IGNORECASE)
    if matt_m:
        next_m = re.search(r"\bStabliste\b", raw_text[matt_m.end():], re.IGNORECASE)
        end = matt_m.end() + (next_m.start() if next_m else len(raw_text))
        section = raw_text[matt_m.start():end]
        print(f"[steel_list_check] Mattenstahlliste section: {len(section)} chars, "
              f"clipped_at={'Stabliste' if next_m else 'EOF'}")
        gw = re.findall(r"Gesamtgewicht\s*:?\s*([\d.,]+)", section, re.IGNORECASE)
        print(f"[steel_list_check] Mattenstahlliste Gesamtgewicht candidates: {gw}")
        if gw:
            val = gw[-1].replace(",", ".")
            print(f"[steel_list_check] Mattenstahlliste Gesamtgewicht (last in section): {val!r}")
            return val

    print("[steel_list_check] Mattenstahlliste Gesamtgewicht: not found")
    return None


# Known Korrosionsschutz (corrosion protection) terms used in German construction.
# FV = feuerverzinkt abbreviation used in Einbauteilliste tables.
_KS_PATTERN = re.compile(
    r"\b(feuerverzinkt[e]?|feuerverz\.|FV|verzinkt[e]?|galvanisiert[e]?"
    r"|thermisch\s+verzinkt|keine|Edelstahl|rostfrei|KTL|blank|Zink"
    r"|Zinklamellen|V2A|V4A|A2|A4|Aluminium|unbeschichtet|beschichtet|Korund)\b",
    re.IGNORECASE,
)


def _normalize_ebt_nr(nr: str) -> str:
    """Normalize numeric EBT codes to zero-padded 5-digit form (3009 → 03009)."""
    s = nr.strip().upper()
    if re.fullmatch(r"\d+", s) and len(s) <= 6:
        return s.zfill(5)
    return s


def _valid_ebt_qty(qty: str, ebt_nr: str) -> bool:
    """Reject qty that is clearly a mis-parsed EBT number or out-of-range value."""
    if not re.fullmatch(r"\d+", qty):
        return False
    if qty == ebt_nr or qty == ebt_nr.lstrip("0"):
        return False
    try:
        n = int(qty)
    except ValueError:
        return False
    return 1 <= n <= 500


def _is_garbage_table_text(text: str) -> bool:
    t = text.strip().lower()
    if not t:
        return True
    garbage_markers = (
        "===", "rotated", "vertical labels", "schwerpunkt",
        "reading-order", "drawing text", "pre-extracted",
    )
    return any(m in t for m in garbage_markers)


def _strip_rotated_section(raw_text: str) -> str:
    """Remove rotated-label dump appended for LLM — not part of Einbauteilliste."""
    return re.split(
        r"\n=== ROTATED / VERTICAL LABELS.*",
        raw_text, maxsplit=1, flags=re.IGNORECASE,
    )[0]


def _parse_ebt_row(line: str, next_line: str | None = None) -> dict | None:
    """Parse one Einbauteilliste row into {ebt_nr, hersteller, bezeichnung, korrosionsschutz, qty}."""
    stripped = line.strip()
    if not stripped or _is_garbage_table_text(stripped):
        return None

    # EBT-Nummer: 4+ digit numeric codes (03009, 15011) OR 2-4 letter prefix codes (RD3001).
    # Single-letter patterns like Q335A (steel mesh grade) are intentionally excluded.
    nr_m = re.match(r"(\d{4,}[A-Z\d-]*|[A-Z]{2,4}\d+[A-Z\d-]*)\s+(.*)", stripped, re.IGNORECASE)
    if not nr_m:
        return None
    ebt_nr = _normalize_ebt_nr(nr_m.group(1).strip())
    rest = nr_m.group(2).strip()

    # Menge (Stück): last integer on the line, or qty alone on the next line
    qty_m = re.search(r"\b(\d+)\s*$", rest)
    if qty_m:
        qty = qty_m.group(1)
        rest_no_qty = rest[: qty_m.start()].strip()
    elif next_line and re.fullmatch(r"\d+", next_line.strip()):
        qty = next_line.strip()
        rest_no_qty = rest
    else:
        return None

    if not _valid_ebt_qty(qty, ebt_nr):
        return None

    # Korrosionsschutz: first known protection term found
    ks_m = _KS_PATTERN.search(rest_no_qty)
    if ks_m:
        korrosionsschutz = ks_m.group(0)
        before_ks = rest_no_qty[: ks_m.start()].strip()
    else:
        korrosionsschutz = ""
        before_ks = rest_no_qty

    # Split remaining into Hersteller (first token) and Bezeichnung (rest)
    parts = before_ks.split(None, 1)
    hersteller = parts[0] if parts else ""
    bezeichnung = parts[1].strip() if len(parts) > 1 else ""

    return {
        "ebt_nr": ebt_nr,
        "hersteller": hersteller,
        "bezeichnung": bezeichnung,
        "korrosionsschutz": korrosionsschutz,
        "qty": qty,
    }


_EBT_START_RE = re.compile(r"^(\d{4,}|[A-Z]{2,4}\d+)", re.IGNORECASE)
_EBT_HEADER_RE = re.compile(
    r"Einbauteilliste|EBT.{0,15}Nummer|Hersteller|Korrosionsschutz"
    r"|Bezeichnung|Menge|Bauteil|je\s+Fertigteil|Stück",
    re.IGNORECASE,
)


_EBT_NR_WORD_RE = re.compile(r"^\d{4,6}$|^[A-Z]{2,4}\d+", re.IGNORECASE)

_EBT_COL_PATTERNS: dict[str, re.Pattern[str]] = {
    "ebt": re.compile(r"nummer|EBT|BIP", re.IGNORECASE),
    "hersteller": re.compile(r"hersteller|manufacturer", re.IGNORECASE),
    "bezeichnung": re.compile(r"bezeichnung|description", re.IGNORECASE),
    "ks": re.compile(r"korrosion|corrosion", re.IGNORECASE),
    "menge": re.compile(r"menge|stück|stuck|unit|pcs", re.IGNORECASE),
}


def _extract_menge_qty(menge_raw: str, ebt_nr: str) -> str | None:
    """Extract qty from Menge column only — reject numbers from other columns."""
    text = menge_raw.strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text) and _valid_ebt_qty(text, ebt_nr):
        return text
    m = re.search(r"\b(\d+)\s*(?:stück|stk|pcs)?\s*$", text, re.IGNORECASE)
    if m and _valid_ebt_qty(m.group(1), ebt_nr):
        return m.group(1)
    return None


def _normalize_ebt_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _strip_leading_manufacturer(bez: str, herst: str) -> str:
    """Drop a leading manufacturer word from a normalized Bezeichnung, if present.

    The manufacturer name is frequently repeated as the first word of the
    description (e.g. Hersteller='Peikko', Bezeichnung='Peikko TWIN 65 …').
    One document may print that prefix and the other omit it, so we normalize it
    away on BOTH sides before comparing.
    """
    bez_n = _normalize_ebt_text(bez)
    herst_n = _normalize_ebt_text(herst)
    if herst_n and bez_n.startswith(herst_n + " "):
        return bez_n[len(herst_n):].strip()
    return bez_n


def _bezeichnung_matches(dr: str, sl: str, dr_herst: str = "", sl_herst: str = "") -> bool:
    """Match Bezeichnung independent of which side carries the manufacturer prefix
    or a partial (truncated) extraction."""
    dr_n = _normalize_ebt_text(dr)
    sl_n = _normalize_ebt_text(sl)
    if dr_n == sl_n:
        return True
    if not dr_n or not sl_n:
        return dr_n == sl_n

    # Compare with the leading manufacturer word removed from each side.
    dr_core = _strip_leading_manufacturer(dr, dr_herst)
    sl_core = _strip_leading_manufacturer(sl, sl_herst)
    if dr_core and dr_core == sl_core:
        return True

    # Tolerate one side carrying a prefix/suffix the other lacks (partial extraction).
    # Guard with a length floor so short strings don't match loosely.
    if len(dr_core) >= 8 and len(sl_core) >= 8 and (
        dr_core.endswith(sl_core) or sl_core.endswith(dr_core)
        or dr_core in sl_core or sl_core in dr_core
    ):
        return True
    return False


def _ebt_field_matches(field: str, dr_val: str, sl_val: str, dr_item: dict, sl_item: dict) -> bool:
    dr_v = (dr_val or "").strip()
    sl_v = (sl_val or "").strip()
    if field == "bezeichnung":
        return _bezeichnung_matches(
            dr_v, sl_v,
            dr_item.get("hersteller", ""),
            sl_item.get("hersteller", ""),
        )
    if field == "hersteller":
        return _normalize_ebt_text(dr_v) == _normalize_ebt_text(sl_v)
    if field == "korrosionsschutz":
        return _normalize_ebt_text(dr_v) == _normalize_ebt_text(sl_v)
    if field == "qty":
        return dr_v == sl_v
    return dr_v == sl_v


def _refine_column_boxes(boxes: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    """Split column boundaries at midpoints so cells don't bleed into neighbours."""
    if len(boxes) < 2:
        return boxes
    ordered = sorted(boxes.items(), key=lambda kv: (kv[1][0] + kv[1][1]) / 2)
    centers = [(name, (x0 + x1) / 2) for name, (x0, x1) in ordered]
    refined: dict[str, tuple[float, float]] = {}
    for i, (name, (x0, x1)) in enumerate(ordered):
        left = x0 - 20
        right = x1 + 20
        if i > 0:
            left = (centers[i - 1][1] + centers[i][1]) / 2
        if i + 1 < len(ordered):
            right = (centers[i][1] + centers[i + 1][1]) / 2
        refined[name] = (left, right)
    return refined


def _extend_box(
    box: tuple[float, float] | None, word: dict,
) -> tuple[float, float]:
    x0, x1 = word["x0"], word["x1"]
    if box is None:
        return (x0, x1)
    return (min(box[0], x0), max(box[1], x1))


def _header_column_boxes(header_row: list[dict]) -> dict[str, tuple[float, float]]:
    """Map Einbauteilliste column names to x ranges from the header row."""
    boxes: dict[str, tuple[float, float]] = {}
    for w in header_row:
        text = w["text"]
        for col, pat in _EBT_COL_PATTERNS.items():
            if pat.search(text):
                boxes[col] = _extend_box(boxes.get(col), w)
    return boxes


def _assign_word_column(
    word: dict, col_boxes: dict[str, tuple[float, float]],
) -> str | None:
    """Return column name whose x-range contains the word center (nearest if overlap)."""
    xc = (word["x0"] + word["x1"]) / 2
    best: tuple[float, str] | None = None
    for col, (x0, x1) in col_boxes.items():
        if x0 - 6 <= xc <= x1 + 6:
            dist = 0 if x0 <= xc <= x1 else min(abs(xc - x0), abs(xc - x1))
            if best is None or dist < best[0]:
                best = (dist, col)
    return best[1] if best else None


def _row_to_columns(
    row: list[dict], col_boxes: dict[str, tuple[float, float]],
) -> dict[str, str]:
    cells: dict[str, list[str]] = {k: [] for k in col_boxes}
    for w in sorted(row, key=lambda w: w["x0"]):
        col = _assign_word_column(w, col_boxes)
        if col:
            cells[col].append(w["text"].strip())
    return {k: " ".join(v).strip() for k, v in cells.items()}


def _find_einbauteilliste_table(words: list[dict]) -> list[dict]:
    """Parse Einbauteilliste by column boundaries from the table header row."""
    anchors = [
        w for w in words
        if re.search(r"einbauteilliste|einbauteil", w["text"], re.IGNORECASE)
    ]
    if not anchors:
        return []

    anchor = max(anchors, key=lambda w: w["top"])
    x_min = anchor["x0"] - 25
    x_max = anchor["x0"] + 520

    # Pass 1 — locate header row in a generous vertical band
    probe = [
        w for w in words
        if anchor["top"] - 10 <= w["top"] <= anchor["bottom"] + 280
        and x_min <= w["x0"] <= x_max
        and w.get("upright", True)
        and not _is_garbage_table_text(w["text"])
    ]
    probe_rows = _cluster_words_into_rows(probe, y_tol=5)

    header_idx: int | None = None
    col_boxes: dict[str, tuple[float, float]] = {}
    for idx, row in enumerate(probe_rows):
        row_lower = " ".join(w["text"] for w in row).lower()
        if "hersteller" in row_lower and ("menge" in row_lower or "stück" in row_lower or "stuck" in row_lower):
            boxes = _header_column_boxes(row)
            if "ebt" in boxes and "menge" in boxes:
                header_idx = idx
                col_boxes = _refine_column_boxes(boxes)
                break

    if header_idx is None or not col_boxes:
        print("[steel_list_check] Einbauteilliste table header not found (column layout)")
        return []

    header_bottom = max(w["bottom"] for w in probe_rows[header_idx])
    y_min = probe_rows[header_idx][0]["top"] - 5
    y_max = header_bottom + 200

    region = [
        w for w in words
        if y_min <= w["top"] <= y_max
        and x_min <= w["x0"] <= x_max
        and w.get("upright", True)
        and not _is_garbage_table_text(w["text"])
    ]
    rows = _cluster_words_into_rows(region, y_tol=5)

    # Re-find header in refined row set
    header_idx = None
    for idx, row in enumerate(rows):
        row_lower = " ".join(w["text"] for w in row).lower()
        if "hersteller" in row_lower and ("menge" in row_lower or "stück" in row_lower or "stuck" in row_lower):
            header_idx = idx
            break

    if header_idx is None:
        return []

    print(f"[steel_list_check] Einbauteilliste columns: {list(col_boxes.keys())}")

    items: list[dict] = []
    pending: dict | None = None

    def _flush_pending() -> None:
        nonlocal pending
        if pending and pending.get("qty"):
            items.append(pending)
        pending = None

    for row in rows[header_idx + 1:]:
        cells = _row_to_columns(row, col_boxes)
        ebt_raw = cells.get("ebt", "")
        ebt_m = re.search(r"(\d{4,6}|[A-Z]{2,4}\d+)", ebt_raw, re.IGNORECASE)

        if ebt_m:
            _flush_pending()
            ebt_nr = _normalize_ebt_nr(ebt_m.group(1))
            qty = _extract_menge_qty(cells.get("menge", ""), ebt_nr)
            hersteller = cells.get("hersteller", "").strip()
            bezeichnung = cells.get("bezeichnung", "").strip()
            ks = cells.get("ks", "").strip()
            if not ks:
                ks_m = _KS_PATTERN.search(bezeichnung)
                ks = ks_m.group(0) if ks_m else ""
            if _is_garbage_table_text(bezeichnung):
                bezeichnung = ""
            row_item = {
                "ebt_nr": ebt_nr,
                "hersteller": hersteller,
                "bezeichnung": bezeichnung,
                "korrosionsschutz": ks,
                "qty": qty or "",
            }
            if qty:
                items.append(row_item)
            else:
                pending = row_item
        elif pending is not None:
            extra_bez = cells.get("bezeichnung", "").strip()
            if extra_bez and not _is_garbage_table_text(extra_bez):
                pending["bezeichnung"] = (pending["bezeichnung"] + " " + extra_bez).strip()
            qty = _extract_menge_qty(cells.get("menge", ""), pending["ebt_nr"])
            if qty:
                pending["qty"] = qty
                items.append(pending)
                pending = None
        elif items and cells.get("bezeichnung"):
            extra = cells["bezeichnung"].strip()
            if extra and not _is_garbage_table_text(extra):
                items[-1]["bezeichnung"] = (items[-1]["bezeichnung"] + " " + extra).strip()

    _flush_pending()

    if items:
        print(f"[steel_list_check] Einbauteilliste (table): {len(items)} items")
        for it in items:
            print(
                f"[steel_list_check]   EBT {it['ebt_nr']}: "
                f"hersteller={it['hersteller']!r}  "
                f"bezeichnung={it['bezeichnung'][:40]!r}  "
                f"ks={it['korrosionsschutz']!r}  qty={it['qty']}"
            )
    return items


def _cluster_words_into_rows(words: list[dict], y_tol: float = 4.5) -> list[list[dict]]:
    """Group word dicts into horizontal table rows."""
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"]))
    rows: list[list[dict]] = []
    current: list[dict] = []
    current_y: float | None = None
    for w in sorted_words:
        y = (w["top"] + w["bottom"]) / 2
        if current_y is None or abs(y - current_y) <= y_tol:
            current.append(w)
            current_y = y if current_y is None else (current_y + y) / 2
        else:
            if current:
                rows.append(sorted(current, key=lambda w: w["x0"]))
            current = [w]
            current_y = y
    if current:
        rows.append(sorted(current, key=lambda w: w["x0"]))
    return rows


def _ebt_item_quality(item: dict) -> int:
    """Score parsed EBT row — higher is more trustworthy."""
    score = 0
    if item.get("hersteller"):
        score += 2
    bez = item.get("bezeichnung", "")
    if bez and not _is_garbage_table_text(bez):
        score += min(len(bez), 40) // 10 + 1
    qty = str(item.get("qty", ""))
    if _valid_ebt_qty(qty, item.get("ebt_nr", "")):
        score += 3
    return score


def _merge_einbauteilliste_items(*sources: list[dict]) -> list[dict]:
    """Merge EBT lists — first source (table parse) wins; line parse fills gaps only."""
    merged: dict[str, dict] = {}
    for items in sources:
        for item in items:
            nr = item["ebt_nr"]
            if nr not in merged:
                merged[nr] = item
    return list(merged.values())


def _find_einbauteilliste_items(raw_text: str) -> list[dict]:
    """Parse EBT rows from the Einbauteilliste section.

    Returns a list of dicts with keys: ebt_nr, hersteller, bezeichnung, korrosionsschutz, qty.
    """
    # Find the start of the Einbauteilliste section (exclude rotated-label dump)
    clean_text = _strip_rotated_section(raw_text)
    section_m = re.search(
        r"(?:Einbauteilliste|einbauteil|\bEBT[-\s]Nummer\b)[^\n]*\n",
        clean_text, re.IGNORECASE,
    )
    if not section_m:
        print("[steel_list_check] Einbauteilliste section not found")
        return []

    # Clip at next major section header (line-start only — avoid inline references)
    next_section_m = re.search(
        r"(?:^|\n)\s*(?:Stabliste|Mattenstahlliste)\b",
        clean_text[section_m.end():], re.IGNORECASE | re.MULTILINE,
    )
    section_end = section_m.end() + (
        next_section_m.start() if next_section_m else 6000
    )
    section_text = clean_text[section_m.start():section_end]

    # Collect non-blank, post-header data lines
    data_lines: list[str] = []
    header_passed = False
    for line in section_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if _EBT_HEADER_RE.search(stripped):
            header_passed = True
            continue
        if not header_passed:
            continue
        data_lines.append(stripped)

    # Process lines with look-behind and look-ahead for Bezeichnung overflow.
    # pdfplumber can split a multi-line table cell across 3 extractions:
    #   non-EBT line (first part)  →  EBT row (empty bezeichnung)  →  non-EBT line (last part)
    # Overflow only applies when the EBT row's own Bezeichnung cell is EMPTY —
    # rows with a full Bezeichnung (03009 etc.) must ignore surrounding metadata
    # lines (Projekt:, zu Plan:, wrapped header fragments) entirely.
    items: list[dict] = []
    pending_before: str = ""
    i = 0
    while i < len(data_lines):
        line = data_lines[i]
        if not _EBT_START_RE.match(line):
            if not _is_garbage_table_text(line):
                pending_before = line
            i += 1
            continue

        item: dict | None = None
        advance = 0

        item = _parse_ebt_row(line, data_lines[i + 1] if i + 1 < len(data_lines) else None)
        if item and not re.search(r"\b\d+\s*$", line) and i + 1 < len(data_lines):
            if re.fullmatch(r"\d+", data_lines[i + 1].strip()):
                advance = 1

        if item is None:
            for extra in (1, 2):
                if i + extra >= len(data_lines):
                    break
                merged = " ".join(data_lines[i: i + extra + 1])
                item = _parse_ebt_row(merged)
                if item:
                    advance = extra
                    break

        if item is None and i + 1 < len(data_lines):
            item = _parse_ebt_row(line, data_lines[i + 1])
            if item:
                advance = 1

        if item:
            if not item["bezeichnung"] and pending_before and not _is_garbage_table_text(pending_before):
                item["bezeichnung"] = pending_before
            tail_idx = i + advance + 1
            if (
                not item["bezeichnung"]
                and tail_idx < len(data_lines)
                and not _EBT_START_RE.match(data_lines[tail_idx])
                and not re.fullmatch(r"\d+", data_lines[tail_idx].strip())
                and not _is_garbage_table_text(data_lines[tail_idx])
            ):
                item["bezeichnung"] = (item["bezeichnung"] + " " + data_lines[tail_idx]).strip()
                advance += 1
            items.append(item)
            pending_before = ""
            i += advance + 1
        else:
            pending_before = ""
            i += 1

    print(f"[steel_list_check] Einbauteilliste: {len(items)} items")
    for it in items:
        print(
            f"[steel_list_check]   EBT {it['ebt_nr']}: "
            f"hersteller={it['hersteller']!r}  "
            f"bezeichnung={it['bezeichnung'][:30]!r}  "
            f"ks={it['korrosionsschutz']!r}  "
            f"qty={it['qty']}"
        )
    return items


# ── Supplementary file extractors ────────────────────────────────────────────

def extract_steel_list_pdf(pdf_path: str) -> dict:
    """Extract steel schedule data from a supplementary Stabliste PDF.

    Reads all pages, collects raw text, and sums Gesamtmasse values.
    The result is passed as `steel_list_data` in GraphState so check nodes
    have access to it without re-reading the file.
    """
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        parts: list[str] = []
        all_words: list[dict] = []
        for i, page in enumerate(pdf.pages):
            raw = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            parts.append(raw)
            all_words.extend(page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False))
            preview = raw[:300].replace("\n", "↵")
            print(f"[steel_list_debug] page {i+1}/{page_count}: {len(raw)} chars | {preview!r}")
    raw_text = "\n".join(parts)

    # Write full raw text to a debug file next to the PDF for manual inspection
    import os as _os
    _debug_path = _os.path.splitext(pdf_path)[0] + "_debug_raw.txt"
    try:
        with open(_debug_path, "w", encoding="utf-8") as _f:
            _f.write(raw_text)
        print(f"[steel_list_debug] raw text written to: {_debug_path}")
    except Exception as _e:
        print(f"[steel_list_debug] could not write debug file: {_e}")

    # Check which section headers are present
    for _hdr in ("Stabliste", "Mattenstahlliste", "Einbauteilliste", "Gesamtgewicht", "Gesamtmasse"):
        _m = re.search(rf"\b{_hdr}\b", raw_text, re.IGNORECASE)
        print(f"[steel_list_debug] header '{_hdr}': {'found at pos ' + str(_m.start()) if _m else 'NOT FOUND'}")

    gesamtmasse            = _find_total_mass(raw_text)
    stabliste_total        = _find_stabliste_total(raw_text)
    mattenstahlliste_total = _find_mattenstahlliste_total(raw_text)
    einbauteilliste_items  = _merge_einbauteilliste_items(
        _find_einbauteilliste_table(all_words),
        _find_einbauteilliste_items(raw_text),
    )
    print(f"[steel_list] pages={page_count}  stab={stabliste_total!r}  matt={mattenstahlliste_total!r}"
          f"  ebt_count={len(einbauteilliste_items)}  chars={len(raw_text)}")
    return {
        "raw_text":              raw_text.strip(),
        "gesamtmasse":           gesamtmasse,
        "stabliste_total":       stabliste_total,
        "mattenstahlliste_total": mattenstahlliste_total,
        "einbauteilliste_items": einbauteilliste_items,
        "page_count":            page_count,
    }


_OVERVIEW_ROW_RE = re.compile(
    # element code        volume           weight           qty    drawing-number (≥5 dash-parts)
    r"^(\d+[A-Z]{0,2}-\d+)\s+([\d.,]+)\s+([\d.,]+)\s+(\d+)\s+([A-Z0-9]+(?:-[A-Z0-9]+){4,})",
    re.MULTILINE | re.IGNORECASE,
)


def extract_overview_plan_pdf(pdf_path: str) -> dict:
    """Extract text content and the element statistics table from an overview plan PDF.

    The result is passed as `overview_plan_data` in GraphState.
    `element_rows` contains one dict per table row with keys:
        code, volume, weight, quantity, drawing_no
    """
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        parts: list[str] = []
        for page in pdf.pages:
            raw = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            parts.append(raw)
    raw_text = "\n".join(parts)

    element_rows: list[dict] = []
    for m in _OVERVIEW_ROW_RE.finditer(raw_text):
        element_rows.append({
            "code":       m.group(1),
            "volume":     m.group(2).replace(",", "."),
            "weight":     m.group(3).replace(",", "."),
            "quantity":   m.group(4),
            "drawing_no": m.group(5).upper(),
        })

    print(f"[overview_plan] pages={page_count}  chars={len(raw_text)}  rows={len(element_rows)}")
    if element_rows:
        print(f"[overview_plan] first row: {element_rows[0]}  last row: {element_rows[-1]}")
    return {
        "raw_text": raw_text.strip(),
        "page_count": page_count,
        "element_rows": element_rows,
    }


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
        f"Gewicht (element weight):    {title_block.get('gewicht') or '(not found)'} to",
        f"Anzahl (element quantity):   {title_block.get('anzahl') or '(not found)'}",
    ]
    parts.extend(tb_lines)
    return "\n".join(parts)
