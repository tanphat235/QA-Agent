"""Format extraction context as LLM-readable text blocks."""
from __future__ import annotations

from qa_agent.extraction.catalog import EXTRACTION_FIELDS
from qa_agent.extraction.context import ExtractionContext

_SECTION_ORDER = (
    ("Title block", (
        "drawing.volumen", "drawing.gewicht", "drawing.anzahl", "drawing.gesamtmasse",
        "drawing.exposition_class", "drawing.betondeckung_cmin_dur", "drawing.betondeckung_delta_c",
        "drawing.betondeckung_cv", "drawing.revision_title_block", "drawing.revision_table_last",
        "drawing.status", "drawing.planfreigabe", "drawing.drawing_no", "drawing.drawing_title",
        "drawing.drawing_name", "drawing.element_code_top_left", "drawing.element_code_from_title",
        "drawing.scale_title_block", "drawing.letzte_stabstahlposition", "drawing.letzte_mattenposition",
    )),
    ("Schedules", (
        "drawing.stabliste_total", "drawing.mattenstahlliste_total",
        "drawing.max_stabliste_pos", "drawing.max_mattenliste_pos",
    )),
    ("Steel List — structured values", (
        "steel_list.gesamtmasse", "steel_list.stabliste_total", "steel_list.mattenstahlliste_total",
    )),
)

_LABEL_BY_KEY = {f.key: f.label for f in EXTRACTION_FIELDS}


def format_extraction_for_llm(ctx: ExtractionContext) -> str:
    """Render PRE-EXTRACTED VALUES + supplementary text blocks for LLM prompts."""
    lines: list[str] = [
        "=== PRE-EXTRACTED VALUES (exact — use these for any calculation/comparison) ===",
        "Available field keys are listed in [brackets] for reference.",
    ]

    for section, keys in _SECTION_ORDER:
        section_lines: list[str] = []
        for key in keys:
            val = ctx.scalars.get(key)
            if val not in (None, "", []):
                label = _LABEL_BY_KEY.get(key, key)
                section_lines.append(f"  [{key}] {label}: {val}")
        if section_lines:
            lines.append(f"[{section}]")
            lines.extend(section_lines)

    ebt = ctx.tables.get("drawing.einbauteilliste") or []
    scale_secs = ctx.tables.get("drawing.scale_sections") or []
    if scale_secs:
        lines.append("[Section view scales]")
        for sec in scale_secs:
            lines.append(
                f"  [{sec.get('scale')}] {sec.get('label', '')[:80]}"
            )

    if ebt:
        lines.append("[Einbauteilliste (drawing) rows]")
        for it in ebt:
            lines.append(
                f"  EBT {it.get('ebt_nr')}: hersteller={it.get('hersteller')!r} "
                f"bezeichnung={it.get('bezeichnung')!r} "
                f"korrosionsschutz={it.get('korrosionsschutz')!r} qty={it.get('qty')}"
            )

    sl_ebt = ctx.tables.get("steel_list.einbauteilliste") or []
    if sl_ebt:
        lines.append("[Steel list Einbauteilliste rows]")
        for it in sl_ebt:
            lines.append(
                f"  EBT {it.get('ebt_nr')}: hersteller={it.get('hersteller')!r} "
                f"bezeichnung={it.get('bezeichnung')!r} "
                f"korrosionsschutz={it.get('korrosionsschutz')!r} qty={it.get('qty')}"
            )

    op_rows = ctx.tables.get("overview_plan.element_rows") or []
    if op_rows:
        lines.append("[Overview plan — structured rows]")
        for r in op_rows:
            lines.append(
                f"  code={r.get('code')} volume={r.get('volume')} weight={r.get('weight')} "
                f"qty={r.get('quantity')} drawing_no={r.get('drawing_no')}"
            )

    sl_raw = ctx.text_blocks.get("steel_list.raw_text") or ""
    if sl_raw:
        lines.append("\n=== STEEL LIST TEXT (pdfplumber extraction) ===")
        lines.append(sl_raw)

    op_raw = ctx.text_blocks.get("overview_plan.raw_text") or ""
    if op_raw:
        lines.append("\n=== OVERVIEW PLAN TEXT (pdfplumber extraction) ===")
        lines.append(op_raw)

    return "\n".join(lines)
