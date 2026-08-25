"""Identifying the element a drawing shows, and its expected steel content band.

The drawing names its element in the title block — "Schalung und Bewehrung FT.-
Wandplatte-Achse A-W503.1" (wall), "Formwork and reinforcement Pr.- TT-Plate-
202-850" (slab), or a "Bauteil / Component" field. Reading that name back out is
the hard part: pdfplumber flattens a sheet metres wide into lines spanning the
whole page, so the title arrives glued to rebar callouts from the same y-band
("20 44 ø 8 L=144cm Formwork and reinforcement Pr.- TT-Plate-202-850"), and the
labels themselves land at unpredictable line numbers across drawing sets.

So this module does not try to pin down one field. It gathers every line that
could name the element, ordered most-trustworthy first, and ``spell_check`` has
the model pick from them. The band comparison itself stays deterministic.
"""
from __future__ import annotations

import re

WALL = "wall"
COLUMN = "column"
BEAM = "beam"
SLAB = "slab"

# Plausible reinforcement ratio per element type [kg/m³]; both bounds inclusive.
STEEL_CONTENT_RANGES: dict[str, tuple[int, int]] = {
    WALL:   (50, 250),
    COLUMN: (80, 350),
    BEAM:   (70, 300),
    SLAB:   (40, 200),
}

DISPLAY_NAMES: dict[str, str] = {
    WALL: "Wall",
    COLUMN: "Column",
    BEAM: "Beam",
    SLAB: "Slab",
}


# Title-block labels that introduce the element name.
_LABEL_RE = re.compile(r"drawing\s*title|bezeichnung|bauteil|component", re.IGNORECASE)

# Recall filter for lines that might name an element, German and English.
# Deliberately over-inclusive: the model decides which line actually names the
# element, so a false positive here is harmless while a miss would make the
# check unusable. Stems are used so compounds match ("Wandplatte", "TT-Platte",
# "Rippenplatte", "Doppelstegplatte" all hit "platte").
_VOCAB_RE = re.compile(
    r"wand|platte|plate|decke|slab|st[uü]tze|stutze|s[aä]ule|saule|column|pfeiler|"
    r"balken|tr[aä]ger|traeger|riegel|unterzug|beam|girder|double\s*tee",
    re.IGNORECASE,
)

_MAX_LINE_CHARS = 200


def normalize_element_type(value: str | None) -> str | None:
    """Accept a model answer only when it names a known element type."""
    candidate = (value or "").strip().lower()
    return candidate if candidate in STEEL_CONTENT_RANGES else None


def element_name_candidates(
    raw_text: str, *fields: str | None, limit: int = 24,
) -> list[str]:
    """Lines that may name the drawing's element, most trustworthy first.

    Order carries the priority the model is told to respect: the extracted
    title-block *fields*, then lines at and just below a title/Bauteil label,
    then any other line using element vocabulary. Incidental mentions come last
    because they may name a different element — a sheet detailing a TT-Plate can
    still carry an "Übersichtsplan FT.-Rippenplatte" cross-reference.
    """
    lines = [ln.strip() for ln in (raw_text or "").split("\n")]

    labelled: list[str] = []
    for i, line in enumerate(lines):
        if _LABEL_RE.search(line):
            labelled.extend(lines[i:i + 3])

    ordered = [str(f or "").strip() for f in fields]
    ordered += labelled
    ordered += [ln for ln in lines if _VOCAB_RE.search(ln)]

    seen: set[str] = set()
    candidates: list[str] = []
    for line in ordered:
        trimmed = line[:_MAX_LINE_CHARS].strip()
        key = trimmed.lower()
        # A line of bare dimensions can name nothing; the slice taken below a
        # label often catches one.
        if not trimmed or key in seen or not any(ch.isalpha() for ch in trimmed):
            continue
        seen.add(key)
        candidates.append(trimmed)
        if len(candidates) >= limit:
            break
    return candidates


def steel_content_range(element_type: str | None) -> tuple[int, int] | None:
    """Expected steel content band [kg/m³] for *element_type*."""
    return STEEL_CONTENT_RANGES.get(element_type or "")


def display_name(element_type: str | None) -> str:
    """Human-readable element type for messages."""
    return DISPLAY_NAMES.get(element_type or "", "Unknown")
