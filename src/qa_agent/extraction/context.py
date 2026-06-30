"""Build structured extraction context from GraphState for user-defined checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qa_agent.state import GraphState


@dataclass
class ExtractionContext:
    """All pdfplumber-extracted data available to user-defined checks."""

    drawing_formatted: str = ""
    drawing_raw_text: str = ""
    title_block: dict = field(default_factory=dict)
    scalars: dict[str, Any] = field(default_factory=dict)
    tables: dict[str, list] = field(default_factory=dict)
    text_blocks: dict[str, str] = field(default_factory=dict)

    def get_scalar(self, key: str) -> Any:
        return self.scalars.get(key)


def build_extraction_context(state: GraphState) -> ExtractionContext:
    """Collect every pre-extracted field from GraphState into one context object."""
    pc = state.get("pdf_content") or {}
    tb = pc.get("title_block") or {}
    sl = state.get("steel_list_data") or {}
    op = state.get("overview_plan_data") or {}
    if not isinstance(op, dict):
        op = {}

    scalars: dict[str, Any] = {
        "drawing.volumen": tb.get("volumen"),
        "drawing.gewicht": tb.get("gewicht"),
        "drawing.anzahl": tb.get("anzahl"),
        "drawing.gesamtmasse": tb.get("gesamtmasse"),
        "drawing.exposition_class": tb.get("exposition_class"),
        "drawing.betondeckung_cmin_dur": tb.get("betondeckung_cmin_dur"),
        "drawing.betondeckung_delta_c": tb.get("betondeckung_delta_c"),
        "drawing.betondeckung_cv": tb.get("betondeckung_cv"),
        "drawing.revision_title_block": tb.get("revision_title_block"),
        "drawing.revision_table_last": tb.get("revision_table_last"),
        "drawing.status": tb.get("status_title_block"),
        "drawing.planfreigabe": tb.get("planfreigabe_text"),
        "drawing.drawing_no": tb.get("drawing_no_value"),
        "drawing.drawing_title": tb.get("drawing_title_value"),
        "drawing.drawing_name": tb.get("drawing_name"),
        "drawing.element_code_top_left": tb.get("element_code_top_left"),
        "drawing.element_code_from_title": tb.get("element_code_from_title"),
        "drawing.scale_title_block": tb.get("scale_title_block"),
        "drawing.letzte_stabstahlposition": tb.get("letzte_stabstahlposition"),
        "drawing.letzte_mattenposition": tb.get("letzte_mattenposition"),
        "drawing.stabliste_total": pc.get("stabliste_total"),
        "drawing.mattenstahlliste_total": pc.get("mattenstahlliste_total"),
        "drawing.max_stabliste_pos": tb.get("max_stabliste_pos"),
        "drawing.max_mattenliste_pos": tb.get("max_mattenliste_pos"),
        "steel_list.gesamtmasse": sl.get("gesamtmasse"),
        "steel_list.stabliste_total": sl.get("stabliste_total"),
        "steel_list.mattenstahlliste_total": sl.get("mattenstahlliste_total"),
    }

    tables: dict[str, list] = {
        "drawing.einbauteilliste": pc.get("einbauteilliste_items") or [],
        "drawing.scale_sections": tb.get("scale_sections") or [],
        "steel_list.einbauteilliste": sl.get("einbauteilliste_items") or [],
        "overview_plan.element_rows": op.get("element_rows") or [],
    }

    text_blocks: dict[str, str] = {
        "drawing.formatted_text": pc.get("formatted") or "",
        "drawing.raw_text": pc.get("raw_text") or "",
        "steel_list.raw_text": (sl.get("raw_text") or "").strip(),
        "overview_plan.raw_text": (op.get("raw_text") or "").strip(),
    }

    return ExtractionContext(
        drawing_formatted=text_blocks["drawing.formatted_text"],
        drawing_raw_text=text_blocks["drawing.raw_text"],
        title_block=tb,
        scalars=scalars,
        tables=tables,
        text_blocks=text_blocks,
    )
