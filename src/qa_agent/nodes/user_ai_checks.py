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
Inspect the drawing (PDF document and the pre-extracted text below) and apply the
QA rules exactly as written. Report ONLY problems you can directly observe.

CRITICAL:
  • Use only what is actually in this drawing — never invent or assume values.
  • If a rule's prerequisite element is missing or unreadable, add that rule's key
    to not_found instead of guessing or silently passing.\
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
        + _OUTRO_TPL.format(check_keys=check_keys)
    )

    human_content: list[dict] = []
    if pdf_data:
        human_content.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
            "cache_control": {"type": "ephemeral"},
        })
    if formatted:
        human_content.append({"type": "text", "text": formatted})
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
