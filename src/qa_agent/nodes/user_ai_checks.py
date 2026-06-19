"""Execute user-defined checks as AI prose rules within their parent domain.

User-created .md rules (not in SHIPPED_BUILTIN_KEYS) are run here and merged
into the domain's issue list (spell / bend / rebar).
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
from qa_agent.rag.retriever import get_check_prompt, get_check_meta
from qa_agent.nodes.issue_filter import OUTPUT_RULES, accept_finding, build_check_issues

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a senior structural QA reviewer for precast concrete wall drawings.
Inspect the drawing (PDF document + the extracted text) and apply the QA rules
exactly as written. You may CALCULATE and COMPARE values to decide a rule.
Report ONLY problems you can directly observe or compute.

CRITICAL:
  • Prefer the "PRE-EXTRACTED VALUES" block — those numbers were parsed
    deterministically and are the source of truth for any calculation/comparison.
    Use the rendered drawing only to locate or confirm things not listed there.
  • Never invent or assume a value. If a value a rule needs is absent/unreadable,
    add that rule's key to not_found instead of guessing or silently passing.\
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
    """Readable block of the deterministically pre-extracted values, so a user
    rule can be evaluated by calculation/comparison rather than visual guessing."""
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
        lines.append("[Einbauteilliste rows]")
        for it in ebt:
            lines.append(
                f"  EBT {it.get('ebt_nr')}: hersteller={it.get('hersteller')!r} "
                f"bezeichnung={it.get('bezeichnung')!r} "
                f"korrosionsschutz={it.get('korrosionsschutz')!r} qty={it.get('qty')}"
            )

    sl = state.get("steel_list_data") or {}
    if sl:
        lines.append("[Steel List file]")
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
    rows = op.get("element_rows") if isinstance(op, dict) else None
    if rows:
        lines.append("[Overview plan rows]")
        for r in rows:
            lines.append(
                f"  code={r.get('code')} volume={r.get('volume')} weight={r.get('weight')} "
                f"qty={r.get('quantity')} drawing_no={r.get('drawing_no')}"
            )

    return "\n".join(lines)


def run_user_ai_checks(domain: str, state: GraphState) -> list:
    """Run enabled user-defined AI checks for *domain*; return issue dicts."""
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

    blocks = []
    for k in active:
        name = meta[k][0]
        prompt = get_check_prompt(domain, k) or ""
        blocks.append(f"CHECK — {name} ({k})\n{prompt.strip()}")
    check_keys = " | ".join(f'"{k}"' for k in active)
    task = (
        "Apply each of the following QA rules to the drawing.\n\n"
        + "\n\n".join(blocks)
        + _CALC_GUIDANCE
        + _OUTRO_TPL.format(check_keys=check_keys)
    )

    facts = _format_extracted_facts(state)

    human_content: list[dict] = []
    if pdf_data:
        human_content.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
            "cache_control": {"type": "ephemeral"},
        })
    if formatted:
        human_content.append({"type": "text", "text": formatted})
    human_content.append({"type": "text", "text": facts})
    human_content.append({"type": "text", "text": task})

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-6",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_UserAiResult).with_retry(stop_after_attempt=2)

    result: _UserAiResult = llm.invoke(  # type: ignore[assignment]
        [SystemMessage(content=_SYSTEM), HumanMessage(content=human_content)],
        config={"callbacks": [_UsageCallback(f"user_ai_{domain}")]},
    )
    print(f"[user_ai_checks][{domain}] raw items from LLM: {len(result.issues)}")

    by_check: dict[str, list[_UserAiIssue]] = {k: [] for k in active}
    for item in result.issues:
        if item.check not in by_check:
            continue
        if not accept_finding(item.description, item.confidence):
            print(f"[user_ai_checks][{domain}] dropped non-violation: {item.description[:80]!r}")
            continue
        by_check[item.check].append(item)

    not_found_set = {k for k in (result.not_found or []) if k in by_check}

    return build_check_issues(
        domain,
        meta,
        by_check,
        not_found_set,
        active,
    )
