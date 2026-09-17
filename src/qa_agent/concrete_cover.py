"""Concrete cover reference data — Table 3.1.

Transcribed from the concrete cover table. The published table gives, per
exposition class, a c_min,dur and Δc value plus one c_nom column per rebar
diameter. Three corrosion mechanisms are tabulated:

  XC1–XC4  carbonation-induced — c_nom rises with the bar diameter
  XD1–XD3  chloride-induced — one c_nom for every diameter
  XS1–XS3  chloride-induced, sea water — one c_nom for every diameter

The title-block BETONDECKUNG fields are compared against the table as:

    Cmin,dur  ==  c_nom(Ø)      — the column matching the check's rebar diameter
    ΔCdev     ==  Δc            — per class, independent of diameter
    Cv        ==  c_nom(Ø) + Δc

Ø10 is the default column. A check may select any other published diameter,
which changes the expected Cmin,dur and Cv but not ΔCdev.

A drawing commonly names more than one class ("XC1, XD1"). Each class states a
cover the element must reach, so the one demanding the most governs and the
others are already satisfied by it — see `governing_class`.

The table's abrasion classes XM1–XM3 are not covered here. They raise c_min by
5 / 10 / 15 mm rather than stating a c_nom of their own ("Concrete cover depends
on the exposure class"), so they modify whichever class governs instead of
competing with it.
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
    "XD1": 15,
    "XD2": 15,
    "XD3": 15,
    "XS1": 15,
    "XS2": 15,
    "XS3": 15,
}

# The chloride classes publish a single c_nom that applies to every diameter.
_FLAT_55 = dict.fromkeys(COVER_DIAMETERS, 55)

# class -> {diameter: c_nom [mm]}
_C_NOM: dict[str, dict[int, int]] = {
    "XC1": {6: 20, 8: 20, 10: 20, 12: 22, 14: 24, 16: 26, 20: 30, 25: 35, 28: 38},
    "XC2": {6: 35, 8: 35, 10: 35, 12: 35, 14: 35, 16: 35, 20: 35, 25: 40, 28: 43},
    "XC3": {6: 35, 8: 35, 10: 35, 12: 35, 14: 35, 16: 35, 20: 35, 25: 40, 28: 43},
    "XC4": {6: 40, 8: 40, 10: 40, 12: 40, 14: 40, 16: 40, 20: 40, 25: 40, 28: 43},
    "XD1": dict(_FLAT_55),
    "XD2": dict(_FLAT_55),
    "XD3": dict(_FLAT_55),
    "XS1": dict(_FLAT_55),
    "XS2": dict(_FLAT_55),
    "XS3": dict(_FLAT_55),
}

# Every class the table covers, for the extraction side to recognise.
EXPOSITION_CLASS_RE = re.compile(r"\bX([CDS])\s*[-–]?\s*([1-4])\b", re.IGNORECASE)

_INT_RE = re.compile(r"\d+")


def parse_diameter(raw: object) -> int | None:
    """Read a stored diameter (e.g. ``"12"``, ``"Ø12"``). None if not a column."""
    match = _INT_RE.search(str(raw or ""))
    if match is None:
        return None
    value = int(match.group())
    return value if value in COVER_DIAMETERS else None


def normalize_class(text: str) -> str | None:
    """The exposition class named in *text* (``"xd 1"`` -> ``"XD1"``), or None.

    Only a class the table actually publishes is returned, so "XD4" — which the
    table has no row for — reads as nothing rather than as a class with no data.
    """
    match = EXPOSITION_CLASS_RE.search(text or "")
    if match is None:
        return None
    code = f"X{match.group(1).upper()}{match.group(2)}"
    return code if code in _C_NOM else None


def parse_classes(text: str) -> list[str]:
    """Every exposition class named in *text*, in order, without repeats.

    A title block states them together: "XC1, XD1" -> ``["XC1", "XD1"]``.
    """
    found: list[str] = []
    for match in EXPOSITION_CLASS_RE.finditer(text or ""):
        code = f"X{match.group(1).upper()}{match.group(2)}"
        if code in _C_NOM and code not in found:
            found.append(code)
    return found


def expected_cover(xc_code: str, diameter: int) -> tuple[int, int, int] | None:
    """Expected (Cmin,dur, ΔCdev, Cv) for one class at rebar *diameter*.

    None when the class is absent from the table or the diameter has no column.
    """
    code = (xc_code or "").strip().upper()
    c_nom = _C_NOM.get(code, {}).get(diameter)
    delta_c = _DELTA_C.get(code)
    if c_nom is None or delta_c is None:
        return None
    return c_nom, delta_c, c_nom + delta_c


def governing_class(codes: list[str] | str, diameter: int) -> str | None:
    """Which of *codes* demands the most cover at *diameter*.

    A drawing that names "XC1, XD1" must satisfy both, and satisfying the
    stricter one satisfies the other — so the comparison is made against the
    class with the largest c_nom, with Δc breaking a tie. Classes the table does
    not publish are ignored; None when none of them is in the table.
    """
    wanted = parse_classes(codes) if isinstance(codes, str) else [
        c for c in (normalize_class(str(x)) for x in codes) if c
    ]
    rated = [(c, _C_NOM[c][diameter], _DELTA_C[c]) for c in wanted if diameter in _C_NOM.get(c, {})]
    if not rated:
        return None
    return max(rated, key=lambda t: (t[1], t[2]))[0]
