import logging
import re
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.outputs import LLMResult

from qa_agent.state import GraphState, Issue
from qa_agent.rag.retriever import get_node_images, get_check_prompt, get_check_meta

logger = logging.getLogger(__name__)

# Must be byte-for-byte identical across all nodes so Anthropic can share the cached PDF prefix.
_COMMON_SYSTEM = """\
You are a senior structural QA reviewer for precast concrete wall drawings. Inspect the PDF drawing visually and technically.

CRITICAL — READ FROM PDF ONLY:
  Every value you use (numbers, labels, part codes, Pos numbers, dimensions, names) MUST be read
  directly from the submitted PDF drawing. Never use memorized data, training knowledge, or cached
  information from prior runs. Never apply product knowledge (e.g. manufacturer names, part
  descriptions) from memory — read only what is visibly printed in the drawing.
  Any number or label not visible in the PDF must not be referenced.

German terminology:
  Schnitt X-X = section/cross-section | Ansicht = elevation/formwork view | Wandansicht = wall elevation
  Bewehrung = reinforcement/rebar | Stabliste = bar list/rebar schedule | Mattenstahlliste = mesh rebar list
  Einbauteilliste = embedded parts list | Montageteilliste = assembly parts list (per element)
  Pos = bar position/mark | Gesamt = total | Stahl = steel | Maßstab / M 1:XX = scale
  Draufsicht = top/plan view | Matten-Schneideskizze = mesh cut sketch | Detail = detail view\
"""

_TASK_INTRO = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.\
"""

# Drop LLM items that describe a passing result instead of an actual violation.
_PASS_ITEM_RE = re.compile(
    r"[-–—]\s*pass(?:es)?\b"
    r"|^pass(?:es)?\b"
    r"|\bthis pass(?:es)?\b"
    r"|\bno\b.{0,80}\bfound\b"
    r"|\bno issue\b"
    r"|\bexactly meets\b"
    r"|\bdeclared\b.{0,30}\bmatches\b.{0,30}\bcalculated\b"
    r"|\bmatches?\b.{0,30}\brequired\b"
    r"|\bvalues?\s+matches?\b",
    re.IGNORECASE | re.MULTILINE,
)

_SPELL_CHECKS = [
    "spelling", "section_name", "component_name", "section_scale", "grid_lines",
    "parts_lists", "parts_quantities", "3d_view", "drawing_title",
]
_CHECK_PROMPTS: dict[str, str] = {k: get_check_prompt("spell", k) for k in _SPELL_CHECKS}
_CHECK_META: dict[str, tuple[str, str, str]] = {k: get_check_meta("spell", k) for k in _SPELL_CHECKS}

_TASK_OUTRO_TPL = """\

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       {check_keys}
  severity:    "error" for clear non-compliance; "warning" for ambiguous or minor
  description: concise — quote the specific text, field, label, or count involved
  page:        1
  location:    specific location (e.g. "Wandansicht element label" or "title block drawing name field")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65
  not_found:   list of check keys where prerequisite drawing elements were absent, e.g. ["grid_lines"]

RULES:
  • OUTPUT ONLY actual problems — items that clearly do not comply.
  • Do NOT output any item to describe a passing check or a verified-correct result.
    (e.g. "all section names present" or "no spelling errors found" → output nothing for that check)
  • An empty issues list means ALL enabled checks passed — that is the correct output when no problems exist.
  • Do NOT flag uncertain or marginally readable text.
  • If prerequisite drawing elements are absent, add the check key to not_found instead of skipping.\
"""


def _build_spell_task(enabled_sub: list[str] | None) -> str:
    active = list(_CHECK_PROMPTS.keys()) if enabled_sub is None else [k for k in enabled_sub if k in _CHECK_PROMPTS]
    check_keys = " | ".join(f'"{k}"' for k in active)
    blocks = "\n\n".join(_CHECK_PROMPTS[k] for k in active)
    return _TASK_INTRO + "\n\n" + blocks + _TASK_OUTRO_TPL.format(check_keys=check_keys)




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


class _SpellIssue(BaseModel):
    check: str = Field(description="spelling | section_name | component_name | section_scale | grid_lines | parts_lists | parts_quantities | 3d_view | drawing_title")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _SpellResult(BaseModel):
    issues: list[_SpellIssue]
    not_found: list[str] = Field(default_factory=list, description="Check keys where prerequisite drawing elements were absent")


def spell_check(state: GraphState) -> dict:
    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]
    enabled_sub = (state.get("enabled_sub_checks") or {}).get("spell")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-6",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_SpellResult).with_retry(stop_after_attempt=2)

    kb_images = get_node_images("spell")
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
    human_content.append({"type": "text", "text": _build_spell_task(enabled_sub)})

    result: _SpellResult = llm.invoke(  # type: ignore[assignment]
        [
            SystemMessage(content=_COMMON_SYSTEM),
            HumanMessage(content=human_content),
        ],
        config={"callbacks": [_UsageCallback("spell_check")]},
    )
    print(f"[usage][spell_check] raw items from LLM: {len(result.issues)}")

    by_check: dict[str, list[_SpellIssue]] = {k: [] for k in _CHECK_META}
    for item in result.issues:
        if item.confidence >= 0.60 and item.check in by_check and not _PASS_ITEM_RE.search(item.description):
            by_check[item.check].append(item)

    not_found_set = set(result.not_found or [])
    issues: list[Issue] = []

    for check_key, (check_name, pass_desc, nf_desc) in _CHECK_META.items():
        if enabled_sub is not None and check_key not in enabled_sub:
            continue
        if check_key in not_found_set:
            issues.append({
                "category": "spell",
                "check_name": check_name,
                "not_found": True,
                "severity": "info",
                "description": nf_desc,
                "page": 1,
                "location": "drawing",
                "confidence": 1.0,
            })
            continue
        found = by_check[check_key]
        passed = len(found) == 0
        summary_desc = pass_desc if passed else (f"FAIL — {found[0].description}" if len(found) == 1 else f"FAIL — {len(found)} issue(s) found.")
        issues.append({
            "category": "spell",
            "check_name": check_name,
            "passed": passed,
            "severity": "info" if passed else "error",
            "description": summary_desc,
            "page": 1,
            "location": "drawing",
            "confidence": 1.0,
        })
        for item in found:
            issues.append({
                "category": "spell",
                "severity": item.severity,
                "description": item.description,
                "page": item.page,
                "location": item.location,
                "confidence": item.confidence,
            })

    return {"spell_issues": issues}
