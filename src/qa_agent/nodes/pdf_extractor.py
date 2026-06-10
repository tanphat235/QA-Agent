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

        return {
            "raw_text": raw_text,
            "title_block": title_block,
            "formatted": _format_for_llm(raw_text),
        }


# ── Title block: value to the right of a label ──────────────────────────────

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


def _extract_title_block(words: list[dict]) -> dict:
    return {
        "letzte_stabstahlposition": _find_number_right_of_label(words, "Stabstahlposition"),
        "letzte_mattenposition":    _find_number_right_of_label(words, "Mattenposition"),
    }


# ── Schedule max-position: spatial column search ────────────────────────────

_POS_X_MARGIN = 8  # pt — column width tolerance around "Pos." header


def _max_pos_in_schedule(words: list[dict], schedule_keyword: str) -> str | None:
    """
    Find the highest Pos number < 100 in the schedule identified by schedule_keyword.

    Strategy:
      1. Locate the schedule label word (e.g. "Stabliste").
      2. Find the "Pos." column header at or below that label.
      3. Collect all integers in the same x-band below the header.
      4. Return the maximum that is < 100.
    """
    # 1. Schedule label
    schedule_word = next(
        (w for w in words if schedule_keyword.lower() in w["text"].lower()), None
    )
    if schedule_word is None:
        return None

    schedule_top = schedule_word["top"]

    # 2. Find "Pos." header below (or at same level as) the schedule label
    pos_headers = [
        w for w in words
        if re.fullmatch(r"Pos\.?", w["text"].strip(), re.IGNORECASE)
        and w["top"] >= schedule_top - 5
    ]
    if not pos_headers:
        return None

    # Take the closest "Pos." header below the schedule label
    pos_header = min(pos_headers, key=lambda w: abs(w["top"] - schedule_top))
    col_x0 = pos_header["x0"] - _POS_X_MARGIN
    col_x1 = pos_header["x1"] + _POS_X_MARGIN
    header_bottom = pos_header["bottom"]

    # 3. Collect all integers in the Pos column below the header
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


# ── LLM text formatter ───────────────────────────────────────────────────────

def _format_for_llm(raw_text: str) -> str:
    return "=== DRAWING TEXT ===\n" + raw_text.strip()
