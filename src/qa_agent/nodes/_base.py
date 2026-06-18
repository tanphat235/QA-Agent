"""Shared utilities for all per-check QA nodes."""
from __future__ import annotations

import logging
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.outputs import LLMResult

from qa_agent.state import GraphState, Issue
from qa_agent.rag.retriever import get_node_images
from qa_agent.nodes.issue_filter import OUTPUT_RULES, accept_finding, clean_finding_description, fail_summary

logger = logging.getLogger(__name__)

# Must be byte-for-byte identical across all nodes so Anthropic can share the cached PDF prefix.
_COMMON_SYSTEM = """\
You are a senior structural QA reviewer for precast concrete wall drawings. Inspect the PDF drawing visually and technically.
German terminology:
  Schnitt X-X = section/cross-section | Ansicht = elevation/formwork view | Wandansicht = wall elevation
  Bewehrung = reinforcement/rebar | Stabliste = bar list/rebar schedule | Mattenstahlliste = mesh rebar list
  Einbauteilliste = embedded parts list | Montageteilliste = assembly parts list (per element)
  Pos = bar position/mark | Gesamt = total | Stahl = steel | Maßstab / M 1:XX = scale
  Draufsicht = top/plan view | Matten-Schneideskizze = mesh cut sketch | Detail = detail view\
"""

_OUTRO = """\

=====================================
OUTPUT FORMAT — one item per finding
=====================================
  severity:    "error" for clear non-compliance; "warning" for ambiguous
  description: concise — quote specific labels, values, or discrepancies
  page:        1
  location:    specific location in the drawing
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65
  not_found:   true if required drawing elements/values were not visible; false otherwise

RULES:
  • Only report issues directly visible and unambiguous.

""" + OUTPUT_RULES


class _Issue(BaseModel):
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _Result(BaseModel):
    issues: list[_Issue]
    not_found: bool = False


class _UsageCallback(BaseCallbackHandler):
    def __init__(self, label: str) -> None:
        self.label = label

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        try:
            msg = response.generations[0][0].message  # type: ignore[attr-defined]
            u = getattr(msg, "response_metadata", {}).get("usage", {})
            if not u:
                u = getattr(msg, "usage_metadata", {}) or {}
            print(
                f"[usage][{self.label}] input={u.get('input_tokens', 0)}"
                f"  cache_create={u.get('cache_creation_input_tokens', 0)}"
                f"  cache_read={u.get('cache_read_input_tokens', 0)}"
                f"  output={u.get('output_tokens', 0)}"
            )
        except Exception as exc:
            print(f"[usage][{self.label}] could not read usage: {exc}")


def run_check(
    state: GraphState,
    check_key: str,
    domain: str,
    issues_key: str,
    check_name: str,
    pass_desc: str,
    nf_desc: str,
    prompt: str,
    confidence_threshold: float = 0.60,
) -> dict:
    """Generic single-check runner used by every per-check node."""
    # Skip if domain not enabled
    enabled = state.get("enabled_checks") or ["spell", "bend", "rebar"]
    if domain not in enabled:
        return {issues_key: []}
    # Skip if sub-check not enabled
    enabled_sub = (state.get("enabled_sub_checks") or {}).get(domain)
    if enabled_sub is not None and check_key not in enabled_sub:
        return {issues_key: []}

    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-6",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=2048,  # type: ignore[call-arg]
    ).with_structured_output(_Result).with_retry(stop_after_attempt=2)

    kb_images = get_node_images(domain)
    human_content: list[dict] = []
    for i, img in enumerate(kb_images):
        block = dict(img)
        if i == len(kb_images) - 1:
            block["cache_control"] = {"type": "ephemeral"}
        human_content.append(block)
    human_content.append({
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
        "cache_control": {"type": "ephemeral"},
    })
    human_content.append({"type": "text", "text": prompt + _OUTRO})

    result: _Result = llm.invoke(  # type: ignore[assignment]
        [
            SystemMessage(content=_COMMON_SYSTEM),
            HumanMessage(content=human_content),
        ],
        config={"callbacks": [_UsageCallback(check_key)]},
    )

    filtered = [
        i for i in result.issues
        if accept_finding(i.description, i.confidence, confidence_threshold)
    ]
    passed = len(filtered) == 0 and not result.not_found

    issues: list[Issue] = []
    if result.not_found:
        issues.append({
            "category": domain,
            "check_name": check_name,
            "not_found": True,
            "severity": "info",
            "description": nf_desc,
            "page": 1,
            "location": "drawing",
            "confidence": 1.0,
        })
    else:
        summary_desc = pass_desc if passed else fail_summary(len(filtered))
        issues.append({
            "category": domain,
            "check_name": check_name,
            "passed": passed,
            "severity": "info" if passed else "error",
            "description": summary_desc,
            "page": 1,
            "location": "drawing",
            "confidence": 1.0,
        })
        for item in filtered:
            issues.append({
                "category": domain,
                "severity": item.severity,
                "description": clean_finding_description(item.description),
                "page": item.page,
                "location": item.location,
                "confidence": item.confidence,
            })

    return {issues_key: issues}
