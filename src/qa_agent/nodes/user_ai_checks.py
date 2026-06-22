"""Execute user-defined checks as AI prose rules within their parent domain.

User-created .md rules (not in SHIPPED_BUILTIN_KEYS) are run here and merged
into the domain's issue list (spell / bend / rebar).

Model routing
─────────────
Text-only checks (requires_vision=false, the default):
  • Input  : extracted text + pre-extracted facts block
  • Model  : claude-haiku-4-5  (cheap, fast)

Vision checks (requires_vision=true in the check's .md):
  • Input  : rendered PDF document + extracted text + facts block
  • Model  : claude-sonnet-4-6  (handles visual layout / table reading)
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.outputs import LLMResult

from qa_agent.state import GraphState
from qa_agent import checks_registry as registry
from qa_agent.rag.retriever import get_check_prompt, get_check_meta, get_check_requires_vision
from qa_agent.nodes.issue_filter import OUTPUT_RULES, accept_finding, build_check_issues

logger = logging.getLogger(__name__)

_SYSTEM_TEXT = """\
You are a senior structural QA reviewer for precast concrete wall drawings.

CRITICAL — READ FROM EXTRACTED TEXT ONLY:
  Every value you use (numbers, labels, part codes, Pos numbers, dimensions, names) MUST be read
  directly from the extracted drawing text provided below. Never use memorized data, training
  knowledge, or information from any previous run or previously seen drawing.
  If a piece of text in the extraction appears fragmented, garbled, or unclear, do NOT reconstruct
  or infer its intended value — report it as unreadable and add the check to not_found instead.
  Never "imply", "infer", or "reconstruct" a value. If you cannot read it directly, it is not_found.

CRITICAL — CALCULATION FROM PRE-EXTRACTED VALUES:
  A block of PRE-EXTRACTED VALUES (deterministically parsed) is provided below the drawing text.
  For any arithmetic comparison (sums, ratios, limits) use those numbers — they are the source of
  truth. If a value a rule needs is absent from both the extracted text and the values block, add
  that rule's key to not_found instead of guessing or silently passing.

CRITICAL — NEVER SILENTLY PASS:
  If any information required by a check is missing, not visible, or not readable in the drawing,
  you MUST add that check key to not_found. Do NOT assume a check passes just because you cannot
  find the relevant elements. Missing prerequisite = not_found, not pass.

German terminology:
  Schnitt X-X = section/cross-section | Ansicht = elevation/formwork view | Wandansicht = wall elevation
  Bewehrung = reinforcement/rebar | Stabliste = bar list/rebar schedule | Mattenstahlliste = mesh rebar list
  Einbauteilliste = embedded parts list | Montageteilliste = assembly parts list (per element)
  Pos = bar position/mark | Gesamt = total | Stahl = steel | Maßstab / M 1:XX = scale
  Draufsicht = top/plan view | Matten-Schneideskizze = mesh cut sketch | Detail = detail view\
"""

_SYSTEM_VISION = """\
You are a senior structural QA reviewer for precast concrete wall drawings.
Inspect the PDF drawing visually and technically.

CRITICAL — PREFER THE RENDERED PDF:
  Read all values (dimensions, labels, table cells, annotations) directly from the rendered PDF.
  Extracted text is provided as a supplementary cross-reference only — pdfplumber may drop or
  mis-align values from graphical views, narrow table columns, or rotated text. Always trust what
  you see in the rendered drawing over the extracted text.

CRITICAL — CALCULATION FROM PRE-EXTRACTED VALUES:
  A block of PRE-EXTRACTED VALUES (deterministically parsed) is also provided. For arithmetic
  checks (sums, ratios, limits) prefer those numbers as the source of truth for calculations.
  If a value is absent from both the PDF and the values block, add that rule's key to not_found.

CRITICAL — NEVER SILENTLY PASS:
  If any information required by a check is missing, not visible, or not readable in the drawing,
  you MUST add that check key to not_found. Do NOT assume a check passes just because you cannot
  find the relevant elements. Missing prerequisite = not_found, not pass.

German terminology:
  Schnitt X-X = section/cross-section | Ansicht = elevation/formwork view | Wandansicht = wall elevation
  Bewehrung = reinforcement/rebar | Stabliste = bar list/rebar schedule | Mattenstahlliste = mesh rebar list
  Einbauteilliste = embedded parts list | Montageteilliste = assembly parts list (per element)
  Pos = bar position/mark | Gesamt = total | Stahl = steel | Maßstab / M 1:XX = scale
  Draufsicht = top/plan view | Matten-Schneideskizze = mesh cut sketch | Detail = detail view\
"""

# Appended after the rules so the model knows HOW to do arithmetic/comparison.
_CALC_GUIDANCE = """\

═══════════════════════════════════
CALCULATION & COMPARISON
═══════════════════════════════════
  • When a rule needs arithmetic (sum, ratio, difference, %) or a comparison
    (A vs B, value vs limit, max of a column vs a title-block value), compute it
    from the PRE-EXTRACTED VALUES above. Work step by step internally.
  • Decimals may use a comma or a dot ("3,21" = "3.21"); treat them as equal.
  • Apply the tolerance the rule states. If the rule gives none:
      – exact match for codes, text and integer counts (Pos, Anzahl, EBT-Nummer);
      – measured quantities (mass, weight, volume, length) match within ±1 %.
  • Flag a finding ONLY when the rule is actually violated after the calculation.
    A rule that holds within tolerance produces NOTHING. Put no working/derivation
    in the description — just state the violated fact and the two values involved.\
"""

_OUTRO_TPL = """\

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       {check_keys}
  severity:    "error" for clear non-compliance; "warning" for ambiguous or minor
  description: concise — quote the specific text, value, label, or location involved
  page:        the 1-based page where the problem appears
  location:    specific location (e.g. "title block", "Schnitt A-A", a label name)
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65
  not_found:   list of check keys whose required drawing elements were absent

RULES:
  • OUTPUT ONLY actual problems — items that clearly violate a rule.
  • Do NOT output an item for a passing/verified-correct rule.
  • If a rule's prerequisites are absent, add its key to not_found instead.

""" + OUTPUT_RULES


class _UserAiIssue(BaseModel):
    check: str
    severity: str = Field(description="error | warning")
    description: str
    page: int = 1
    location: str = ""
    confidence: float = Field(default=0.8, description="0.65–1.0")


class _UserAiResult(BaseModel):
    issues: list[_UserAiIssue] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)


class _UsageCallback(BaseCallbackHandler):
    def __init__(self, label: str) -> None:
        self.label = label

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        try:
            msg = response.generations[0][0].message  # type: ignore[attr-defined]
            u = getattr(msg, "response_metadata", {}).get("usage", {}) or getattr(msg, "usage_metadata", {}) or {}
            print(f"[usage][{self.label}] input={u.get('input_tokens', 0)} output={u.get('output_tokens', 0)}")
        except Exception as exc:
            print(f"[usage][{self.label}] could not read usage: {exc}")


def _format_extracted_facts(state: GraphState) -> str:
    """Build the supplementary data block passed to every user-defined check.

    Contains three layers, mirroring what built-in checks have access to:
      1. PRE-EXTRACTED VALUES  — deterministic key-value pairs from title block,
                                 schedule totals, EBT table rows, overview plan rows.
      2. STEEL LIST TEXT       — full pdfplumber text of the supplementary steel-list
                                 file (if uploaded), so checks can read any cell.
      3. OVERVIEW PLAN TEXT    — full pdfplumber text of the overview plan file
                                 (if uploaded), so checks can read any row or column.
    """
    pc = state.get("pdf_content") or {}
    tb = pc.get("title_block") or {}
    lines: list[str] = [
        "=== PRE-EXTRACTED VALUES (exact — use these for any calculation/comparison) ==="
    ]

    def add(label: str, value) -> None:
        if value not in (None, "", []):
            lines.append(f"  {label}: {value}")

    lines.append("[Title block]")
    add("Volumen (m³)", tb.get("volumen"))
    add("Gewicht (to)", tb.get("gewicht"))
    add("Anzahl", tb.get("anzahl"))
    add("Gesamtmasse total steel (kg)", tb.get("gesamtmasse"))
    add("Exposition class", tb.get("exposition_class"))
    add("Betondeckung Cmin,dur", tb.get("betondeckung_cmin_dur"))
    add("Betondeckung ΔCdev", tb.get("betondeckung_delta_c"))
    add("Betondeckung Cv", tb.get("betondeckung_cv"))
    add("Revision (title block)", tb.get("revision_title_block"))
    add("Revision (last in table)", tb.get("revision_table_last"))
    add("Status", tb.get("status_title_block"))
    add("Planfreigabe", tb.get("planfreigabe_text"))
    add("Drawing No.", tb.get("drawing_no_value"))
    add("Drawing Title", tb.get("drawing_title_value"))
    add("letzte Stabstahlposition", tb.get("letzte_stabstahlposition"))
    add("letzte Mattenposition", tb.get("letzte_mattenposition"))

    lines.append("[Schedules]")
    add("Stabliste Gesamtmasse (kg)", pc.get("stabliste_total"))
    add("Mattenstahlliste Gesamtgewicht (kg)", pc.get("mattenstahlliste_total"))
    add("Stabliste max Pos (<100)", tb.get("max_stabliste_pos"))
    add("Mattenstahlliste max Pos (<100)", tb.get("max_mattenliste_pos"))

    ebt = pc.get("einbauteilliste_items") or []
    if ebt:
        lines.append("[Einbauteilliste (drawing) rows]")
        for it in ebt:
            lines.append(
                f"  EBT {it.get('ebt_nr')}: hersteller={it.get('hersteller')!r} "
                f"bezeichnung={it.get('bezeichnung')!r} "
                f"korrosionsschutz={it.get('korrosionsschutz')!r} qty={it.get('qty')}"
            )

    sl = state.get("steel_list_data") or {}
    if sl:
        lines.append("[Steel List — structured values]")
        add("Gesamtmasse (kg)", sl.get("gesamtmasse"))
        add("Stabliste total (kg)", sl.get("stabliste_total"))
        add("Mattenstahlliste total (kg)", sl.get("mattenstahlliste_total"))
        for it in (sl.get("einbauteilliste_items") or []):
            lines.append(
                f"  EBT {it.get('ebt_nr')}: hersteller={it.get('hersteller')!r} "
                f"bezeichnung={it.get('bezeichnung')!r} "
                f"korrosionsschutz={it.get('korrosionsschutz')!r} qty={it.get('qty')}"
            )

    op = state.get("overview_plan_data") or {}
    op_rows = op.get("element_rows") if isinstance(op, dict) else None
    if op_rows:
        lines.append("[Overview plan — structured rows]")
        for r in op_rows:
            lines.append(
                f"  code={r.get('code')} volume={r.get('volume')} weight={r.get('weight')} "
                f"qty={r.get('quantity')} drawing_no={r.get('drawing_no')}"
            )

    # ── Full pdfplumber text of supplementary files ───────────────────────────
    # Appended so checks that need to read any cell or row have the raw text.
    sl_raw = (sl.get("raw_text") or "").strip() if sl else ""
    if sl_raw:
        lines.append("\n=== STEEL LIST TEXT (pdfplumber extraction) ===")
        lines.append(sl_raw)

    op_raw = (op.get("raw_text") or "").strip() if isinstance(op, dict) else ""
    if op_raw:
        lines.append("\n=== OVERVIEW PLAN TEXT (pdfplumber extraction) ===")
        lines.append(op_raw)

    return "\n".join(lines)


def _build_task(keys: list[str], meta: dict, domain: str) -> str:
    blocks = []
    for k in keys:
        name = meta[k][0]
        prompt = get_check_prompt(domain, k) or ""
        blocks.append(f"CHECK — {name} ({k})\n{prompt.strip()}")
    check_keys = " | ".join(f'"{k}"' for k in keys)
    return (
        "Apply each of the following QA rules to the drawing.\n\n"
        + "\n\n".join(blocks)
        + _CALC_GUIDANCE
        + _OUTRO_TPL.format(check_keys=check_keys)
    )


def _invoke_group(
    keys: list[str],
    meta: dict,
    domain: str,
    facts: str,
    formatted: str,
    pdf_data: str | None,
    use_vision: bool,
) -> _UserAiResult:
    """Call the LLM for one routing group (text-only or vision).

    Vision group  → claude-sonnet-4-6, PDF + formatted text + facts
    Text-only group → claude-haiku-4-5, formatted text + facts
    Both groups use production-grade system prompts identical in quality to
    built-in checks (NEVER SILENTLY PASS, German terminology, etc.).
    """
    task = _build_task(keys, meta, domain)

    if use_vision:
        model = "claude-sonnet-4-6"
        system = _SYSTEM_VISION
        human_content: list[dict] = []
        # PDF first — the model reads the rendered drawing as the primary source.
        if pdf_data:
            human_content.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
                "cache_control": {"type": "ephemeral"},
            })
        # Extracted text as supplementary cross-reference.
        if formatted:
            human_content.append({"type": "text", "text": formatted})
        # Pre-extracted facts block (deterministic values for calculations).
        human_content.append({"type": "text", "text": facts})
    else:
        model = "claude-haiku-4-5"
        system = _SYSTEM_TEXT
        human_content = []
        # Extracted text — primary source for text-only checks.
        if formatted:
            human_content.append({
                "type": "text",
                "text": formatted,
                "cache_control": {"type": "ephemeral"},
            })
        # Pre-extracted facts block (deterministic values for calculations).
        human_content.append({"type": "text", "text": facts})

    human_content.append({"type": "text", "text": task})

    label = f"user_ai_{domain}_{'vision' if use_vision else 'text'}"
    print(f"[user_ai_checks][{domain}] {'vision' if use_vision else 'text'} group → {model}: {keys}")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model=model,  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=8192,  # type: ignore[call-arg]
    ).with_structured_output(_UserAiResult).with_retry(stop_after_attempt=2)

    return llm.invoke(  # type: ignore[return-value]
        [SystemMessage(content=system), HumanMessage(content=human_content)],
        config={"callbacks": [_UsageCallback(label)]},
    )


def run_user_ai_checks(domain: str, state: GraphState) -> list:
    """Run enabled user-defined AI checks for *domain*; return issue dicts.

    Checks are split by their ``## Requires Vision`` flag:
      • false (default) → claude-haiku-4-5, text + facts only
      • true            → claude-sonnet-4-6, PDF document + text + facts
    """
    enabled_sub = (state.get("enabled_sub_checks") or {}).get(domain)
    all_keys = registry.list_user_ai_check_keys(domain)
    active = [k for k in all_keys if enabled_sub is None or k in (enabled_sub or [])]
    if not active:
        return []

    meta = {k: get_check_meta(domain, k) for k in active}
    print(f"[user_ai_checks][{domain}] running {len(active)} user check(s): {active}")

    pdf_content = state.get("pdf_content") or {}
    formatted: str = pdf_content.get("formatted") or ""
    pdf_data: str | None = state.get("pdf_data")  # type: ignore[assignment]
    facts = _format_extracted_facts(state)

    # Route checks by vision requirement
    text_keys  = [k for k in active if not get_check_requires_vision(domain, k)]
    vision_keys = [k for k in active if get_check_requires_vision(domain, k)]

    if vision_keys and not pdf_data:
        # No PDF available — downgrade vision checks to text-only with a warning
        print(
            f"[user_ai_checks][{domain}] WARNING: {vision_keys} require vision but "
            f"pdf_data is absent — falling back to text-only (claude-haiku-4-5)"
        )
        text_keys  = active
        vision_keys = []

    # Collect all raw issues and not_found across both groups
    by_check: dict[str, list[_UserAiIssue]] = {k: [] for k in active}
    not_found_set: set[str] = set()

    for group_keys, use_vision in ((text_keys, False), (vision_keys, True)):
        if not group_keys:
            continue
        result = _invoke_group(group_keys, meta, domain, facts, formatted, pdf_data, use_vision)
        print(f"[user_ai_checks][{domain}] {'vision' if use_vision else 'text'} raw items: {len(result.issues)}")

        for item in result.issues:
            if item.check not in by_check:
                continue
            if not accept_finding(item.description, item.confidence):
                print(f"[user_ai_checks][{domain}] dropped non-violation: {item.description[:80]!r}")
                continue
            by_check[item.check].append(item)

        not_found_set |= {k for k in (result.not_found or []) if k in by_check}

    return build_check_issues(domain, meta, by_check, not_found_set, active)
