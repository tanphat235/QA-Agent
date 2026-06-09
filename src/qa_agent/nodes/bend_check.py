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

_TASK_INTRO = """\
Review the bar schedule (Stabliste), mesh schedule (Mattenstahlliste), and rebar schemas in this structural drawing.
Report ONLY issues you can directly observe from clearly visible values in the PDF.\
"""

_BEND_CHECKS = [
    "pos_coverage", "mesh_pos", "mesh_ratio",
    "mass_arithmetic", "bending_angle", "bar_length",
]
_CHECK_PROMPTS: dict[str, str] = {k: get_check_prompt("bend", k) for k in _BEND_CHECKS}
_CHECK_META: dict[str, tuple[str, str, str]] = {k: get_check_meta("bend", k) for k in _BEND_CHECKS}

_TASK_OUTRO_TPL = """\

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       {check_keys}
  severity:    "error" for clear non-compliance; "warning" for borderline or ambiguous
  description: concise — quote Pos number, computed vs shown value, or ratio result
  page:        1
  location:    specific location (e.g. "Stabliste row Pos 12" or "Bewehrung Schnitt 3-3")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65
  not_found:   list of check keys where required drawing information was not visible, e.g. ["mesh_pos", "mesh_ratio"]

RULES:
  • OUTPUT ONLY actual problems — values that do not comply, missing items, or clear errors.
  • Do NOT output any item to describe a passing check, a matching value, or a verified-correct result.
    (e.g. "all values match" or "no issues found for X" → output nothing for that check)
  • An empty issues list means ALL enabled checks passed — that is the correct output when no problems exist.
  • Do NOT infer or estimate values not shown.
  • If required information is absent from the drawing, add the check key to not_found instead of skipping.\
"""


def _build_bend_task(enabled_sub: list[str] | None) -> str:
    active = list(_CHECK_PROMPTS.keys()) if enabled_sub is None else [k for k in enabled_sub if k in _CHECK_PROMPTS]
    check_keys = " | ".join(f'"{k}"' for k in active)
    blocks = "\n\n".join(_CHECK_PROMPTS[k] for k in active)
    return _TASK_INTRO + "\n\n" + blocks + _TASK_OUTRO_TPL.format(check_keys=check_keys)



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

_HIGH_CONFIDENCE_CHECKS = {"pos_coverage"}


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


class _BendIssue(BaseModel):
    check: str = Field(description="pos_coverage | mesh_pos | mesh_ratio | mass_arithmetic | bending_angle | bar_length")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _BendResult(BaseModel):
    issues: list[_BendIssue]
    not_found: list[str] = Field(default_factory=list, description="Check keys where required drawing information was not visible")


def bend_check(state: GraphState) -> dict:
    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]
    enabled_sub = (state.get("enabled_sub_checks") or {}).get("bend")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-6",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_BendResult).with_retry(stop_after_attempt=2)

    kb_images = get_node_images("bend")
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
    human_content.append({"type": "text", "text": _build_bend_task(enabled_sub)})

    result: _BendResult = llm.invoke(  # type: ignore[assignment]
        [
            SystemMessage(content=_COMMON_SYSTEM),
            HumanMessage(content=human_content),
        ],
        config={"callbacks": [_UsageCallback("bend_check")]},
    )
    print(f"[usage][bend_check] raw items from LLM: {len(result.issues)}")

    by_check: dict[str, list[_BendIssue]] = {k: [] for k in _CHECK_META}
    for item in result.issues:
        if item.check not in by_check:
            continue
        threshold = 0.80 if item.check in _HIGH_CONFIDENCE_CHECKS else 0.60
        if item.confidence >= threshold and not _PASS_ITEM_RE.search(item.description):
            by_check[item.check].append(item)

    not_found_set = set(result.not_found or [])
    issues: list[Issue] = []

    for check_key, (check_name, pass_desc, nf_desc) in _CHECK_META.items():
        if enabled_sub is not None and check_key not in enabled_sub:
            continue
        if check_key in not_found_set:
            issues.append({
                "category": "bend",
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
            "category": "bend",
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
                "category": "bend",
                "severity": item.severity,
                "description": item.description,
                "page": item.page,
                "location": item.location,
                "confidence": item.confidence,
            })

    return {"bend_issues": issues}
