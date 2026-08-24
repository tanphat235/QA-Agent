"""Concrete cover reference data — Table 3.1.

Transcribed from the concrete cover table, carbonation-induced corrosion section
(classes XC1–XC4). The published table gives, per exposition class, a c_min and
Δc value plus one c_nom column per rebar diameter. Only Δc and the c_nom columns
are needed here; c_min is documented in the check's .md description for reference.

The title-block BETONDECKUNG fields are compared against the table as:

    Cmin,dur  ==  c_nom(Ø)      — the column matching the check's rebar diameter
    ΔCdev     ==  Δc            — per class, independent of diameter
    Cv        ==  c_nom(Ø) + Δc

Ø10 is the default column. A check may select any other published diameter,
which changes the expected Cmin,dur and Cv but not ΔCdev.
"""
from __future__ import annotations

import re

# Diameters [mm] that Table 3.1 publishes a c_nom column for.
COVER_DIAMETERS: tuple[int, ...] = (6, 8, 10, 12, 14, 16, 20, 25, 28)

DEFAULT_DIAMETER = 10

# class -> Δc [mm]
_DELTA_C: dict[str, int] = {
    "XC1": 10,
    "XC2": 15,
    "XC3": 15,
    "XC4": 15,
}

# class -> {diameter: c_nom [mm]}
_C_NOM: dict[str, dict[int, int]] = {
    "XC1": {6: 20, 8: 20, 10: 20, 12: 22, 14: 24, 16: 26, 20: 30, 25: 35, 28: 38},
    "XC2": {6: 35, 8: 35, 10: 35, 12: 35, 14: 35, 16: 35, 20: 35, 25: 40, 28: 43},
    "XC3": {6: 35, 8: 35, 10: 35, 12: 35, 14: 35, 16: 35, 20: 35, 25: 40, 28: 43},
    "XC4": {6: 40, 8: 40, 10: 40, 12: 40, 14: 40, 16: 40, 20: 40, 25: 40, 28: 43},
}

_INT_RE = re.compile(r"\d+")


def parse_diameter(raw: object) -> int | None:
    """Read a stored diameter (e.g. ``"12"``, ``"Ø12"``). None if not a column."""
    match = _INT_RE.search(str(raw or ""))
    if match is None:
        return None
    value = int(match.group())
    return value if value in COVER_DIAMETERS else None


def expected_cover(xc_code: str, diameter: int) -> tuple[int, int, int] | None:
    """Expected (Cmin,dur, ΔCdev, Cv) for *xc_code* at rebar *diameter*.

    None when the class is absent from the table or the diameter has no column.
    """
    code = (xc_code or "").strip().upper()
    c_nom = _C_NOM.get(code, {}).get(diameter)
    delta_c = _DELTA_C.get(code)
    if c_nom is None or delta_c is None:
        return None
    return c_nom, delta_c, c_nom + delta_c
