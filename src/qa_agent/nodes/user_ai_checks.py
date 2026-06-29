"""Execute user-defined checks as AI prose rules within their parent domain.

User-created .md rules (not in SHIPPED_BUILTIN_KEYS) are run here and merged
into the domain's issue list (spell / bend / rebar).

Data sources (user-defined checks MUST use only these):
  • qa_agent.extraction.build_extraction_context  — pdfplumber structured fields
  • qa_agent.extraction.format_extraction_for_llm — text block for LLM
  • qa_agent.extraction.run_deterministic_check   — Python evaluators (no LLM)
  • PDF vision (Sonnet) when requires_vision=true in the check .md

Model routing
─────────────
Text-only checks (requires_vision=false, the default):
  • Input  : drawing formatted text + extraction context block
  • Model  : claude-haiku-4-5

Vision checks (requires_vision=true):
  • Input  : PDF document + formatted text + extraction context block
  • Model  : claude-sonnet-4-6
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
from qa_agent.extraction import (
    build_extraction_context,
    format_extraction_for_llm,
    list_extraction_fields,
    run_deterministic_check,
)

logger = logging.getLogger(__name__)

_FIELDS_INTRO = """\
The PRE-EXTRACTED VALUES block lists every pdfplumber field available from the backend.
Use field keys in [brackets] (e.g. [drawing.element_code_top_left]) when citing values.
Only use values present in that block or readable from the drawing text — never invent data.\
"""

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


def _build_task(keys: list[str], meta: dict, domain: str) -> str:
    blocks = []
    for k in keys:
        name = meta[k][0]
        prompt = get_check_prompt(domain, k) or ""
        blocks.append(f"CHECK — {name} ({k})\n{prompt.strip()}")
    check_keys = " | ".join(f'"{k}"' for k in keys)
    field_count = len(list_extraction_fields())
    return (
        _FIELDS_INTRO + f"\n({field_count} backend extraction fields available.)\n\n"
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
    """Call the LLM for one routing group (text-only or vision)."""
    task = _build_task(keys, meta, domain)

    if use_vision:
        model = "claude-sonnet-4-6"
        system = _SYSTEM_VISION
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
    else:
        model = "claude-haiku-4-5"
        system = _SYSTEM_TEXT
        human_content = []
        if formatted:
            human_content.append({
                "type": "text",
                "text": formatted,
                "cache_control": {"type": "ephemeral"},
            })
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


def _apply_deterministic_checks(
    state: GraphState,
    active: list[str],
    by_check: dict[str, list[_UserAiIssue]],
    not_found_set: set[str],
) -> list[str]:
    """Run registered Python evaluators; return check keys handled (skip LLM)."""
    ctx = build_extraction_context(state)
    handled: list[str] = []

    for key in active:
        result = run_deterministic_check(key, state, ctx)
        if result is None:
            continue
        handled.append(key)
        if result.not_found:
            not_found_set.add(key)
        for item in result.issues:
            by_check[key].append(_UserAiIssue(
                check=item.check,
                severity=item.severity,
                description=item.description,
                page=item.page,
                location=item.location,
                confidence=item.confidence,
            ))

    return handled


def run_user_ai_checks(domain: str, state: GraphState) -> list:
    """Run enabled user-defined AI checks for *domain*; return issue dicts."""
    enabled_sub = (state.get("enabled_sub_checks") or {}).get(domain)
    all_keys = registry.list_user_ai_check_keys(domain)
    active = [k for k in all_keys if enabled_sub is None or k in (enabled_sub or [])]
    if not active:
        return []

    meta = {k: get_check_meta(domain, k) for k in active}
    print(f"[user_ai_checks][{domain}] running {len(active)} user check(s): {active}")

    ctx = build_extraction_context(state)
    formatted = ctx.drawing_formatted
    facts = format_extraction_for_llm(ctx)
    pdf_data: str | None = state.get("pdf_data")  # type: ignore[assignment]

    by_check: dict[str, list[_UserAiIssue]] = {k: [] for k in active}
    not_found_set: set[str] = set()

    handled = _apply_deterministic_checks(state, active, by_check, not_found_set)
    llm_active = [k for k in active if k not in handled]

    text_keys = [k for k in llm_active if not get_check_requires_vision(domain, k)]
    vision_keys = [k for k in llm_active if get_check_requires_vision(domain, k)]

    if vision_keys and not pdf_data:
        print(
            f"[user_ai_checks][{domain}] WARNING: {vision_keys} require vision but "
            f"pdf_data is absent — falling back to text-only (claude-haiku-4-5)"
        )
        text_keys = llm_active
        vision_keys = []

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
