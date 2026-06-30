"""Catalog of PDF fields available to user-defined checks."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractField:
    key: str
    label: str
    source: str
    description: str
    kind: str  # scalar | table | text_block


EXTRACTION_FIELDS: tuple[ExtractField, ...] = (
    # ── Drawing (main PDF) — title block ─────────────────────────────────────
    ExtractField("drawing.volumen", "Volumen (m³)", "drawing", "Title block element volume", "scalar"),
    ExtractField("drawing.gewicht", "Gewicht (to)", "drawing", "Title block element weight", "scalar"),
    ExtractField("drawing.anzahl", "Anzahl", "drawing", "Title block element quantity", "scalar"),
    ExtractField("drawing.gesamtmasse", "Gesamtmasse total steel (kg)", "drawing", "Total steel mass in title block", "scalar"),
    ExtractField("drawing.exposition_class", "Exposition class", "drawing", "XC exposure class", "scalar"),
    ExtractField("drawing.betondeckung_cmin_dur", "Betondeckung Cmin,dur", "drawing", "Concrete cover Cmin,dur (mm)", "scalar"),
    ExtractField("drawing.betondeckung_delta_c", "Betondeckung ΔCdev", "drawing", "Concrete cover ΔCdev (mm)", "scalar"),
    ExtractField("drawing.betondeckung_cv", "Betondeckung Cv", "drawing", "Concrete cover Cv (mm)", "scalar"),
    ExtractField("drawing.revision_title_block", "Revision (title block)", "drawing", "Revision shown in title block", "scalar"),
    ExtractField("drawing.revision_table_last", "Revision (last in table)", "drawing", "Last revision row in history table", "scalar"),
    ExtractField("drawing.status", "Status", "drawing", "Drawing status code (P/A/F)", "scalar"),
    ExtractField("drawing.planfreigabe", "Planfreigabe", "drawing", "Planfreigabe label text", "scalar"),
    ExtractField("drawing.drawing_no", "Drawing No.", "drawing", "Drawing number in title block", "scalar"),
    ExtractField("drawing.drawing_title", "Drawing Title", "drawing", "Full drawing title / Bezeichnung", "scalar"),
    ExtractField("drawing.drawing_name", "Drawing name (top of sheet)", "drawing", "Prominent text cluster at top of sheet", "scalar"),
    ExtractField("drawing.element_code_top_left", "Element code (top-left label)", "drawing", "Element code label at top-left (e.g. 201-851)", "scalar"),
    ExtractField("drawing.element_code_from_title", "Element code (Drawing Title suffix)", "drawing", "Numeric suffix parsed from Drawing Title", "scalar"),
    ExtractField("drawing.scale_title_block", "Scale (title block)", "drawing", "All Maßstab / Scale ratios in title block (e.g. 1:25, 1:10, 1:5)", "scalar"),
    ExtractField("drawing.scale_sections", "Scale (section views)", "drawing", "Per-view scales on Schnitt/Ansicht/Detail labels", "table"),
    ExtractField("drawing.letzte_stabstahlposition", "letzte Stabstahlposition", "drawing", "Last bar Pos in title block", "scalar"),
    ExtractField("drawing.letzte_mattenposition", "letzte Mattenposition", "drawing", "Last mesh Pos in title block", "scalar"),
    # ── Drawing — schedules ───────────────────────────────────────────────────
    ExtractField("drawing.stabliste_total", "Stabliste Gesamtmasse (kg)", "drawing", "Stabliste schedule total mass", "scalar"),
    ExtractField("drawing.mattenstahlliste_total", "Mattenstahlliste Gesamtgewicht (kg)", "drawing", "Mattenstahlliste schedule total weight", "scalar"),
    ExtractField("drawing.max_stabliste_pos", "Stabliste max Pos (<100)", "drawing", "Highest Pos number in Stabliste", "scalar"),
    ExtractField("drawing.max_mattenliste_pos", "Mattenstahlliste max Pos (<100)", "drawing", "Highest Pos in Mattenstahlliste", "scalar"),
    ExtractField("drawing.einbauteilliste", "Einbauteilliste rows", "drawing", "Embedded parts table rows from drawing", "table"),
    # ── Drawing — full text ───────────────────────────────────────────────────
    ExtractField("drawing.formatted_text", "Drawing formatted text", "drawing", "Full pdfplumber text + pre-extracted title block header", "text_block"),
    ExtractField("drawing.raw_text", "Drawing raw text", "drawing", "Plain pdfplumber text extraction", "text_block"),
    # ── Supplementary files ───────────────────────────────────────────────────
    ExtractField("steel_list.gesamtmasse", "Steel list Gesamtmasse (kg)", "steel_list", "Total mass from steel list PDF", "scalar"),
    ExtractField("steel_list.stabliste_total", "Steel list Stabliste total (kg)", "steel_list", "Stabliste total from steel list PDF", "scalar"),
    ExtractField("steel_list.mattenstahlliste_total", "Steel list Mattenstahlliste total (kg)", "steel_list", "Mattenstahlliste total from steel list PDF", "scalar"),
    ExtractField("steel_list.einbauteilliste", "Steel list Einbauteilliste rows", "steel_list", "EBT rows from steel list PDF", "table"),
    ExtractField("steel_list.raw_text", "Steel list raw text", "steel_list", "Full pdfplumber text of steel list PDF", "text_block"),
    ExtractField("overview_plan.element_rows", "Overview plan element rows", "overview_plan", "Element statistics table rows", "table"),
    ExtractField("overview_plan.raw_text", "Overview plan raw text", "overview_plan", "Full pdfplumber text of overview plan PDF", "text_block"),
)


def list_extraction_fields() -> list[dict]:
    """Return catalog entries as JSON-serializable dicts (for frontend API)."""
    return [
        {
            "key": f.key,
            "label": f.label,
            "source": f.source,
            "description": f.description,
            "kind": f.kind,
        }
        for f in EXTRACTION_FIELDS
    ]
