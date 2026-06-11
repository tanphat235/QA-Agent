import logging
import re
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.outputs import LLMResult

from qa_agent.state import GraphState, Issue
from qa_agent.rag.retriever import get_check_prompt, get_check_meta

logger = logging.getLogger(__name__)

# Must be byte-for-byte identical across all nodes so Anthropic can share the cached text prefix.
_COMMON_SYSTEM = """\
You are a senior structural QA reviewer for precast concrete wall drawings. Inspect the PDF drawing visually and technically.

CRITICAL — READ FROM EXTRACTED TEXT ONLY:
  Every value you use (numbers, labels, part codes, Pos numbers, dimensions, names) MUST be read
  directly from the extracted drawing text provided below. Never use memorized data, training
  knowledge, or information from any previous run or previously seen drawing.
  If a piece of text in the extraction appears fragmented, garbled, or unclear, do NOT reconstruct
  or infer its intended value — report it as unreadable and add the check to not_found instead.
  Never "imply", "infer", or "reconstruct" a value. If you cannot read it directly, it is not_found.

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
The drawing content below was extracted from a precast wall structural drawing PDF.
Inspect the text and tables and report ONLY issues you can directly observe.\
"""

# Drop LLM items that describe a passing result instead of an actual violation.
_PASS_ITEM_RE = re.compile(
    r"[-–—]\s*pass(?:es)?\b"
    r"|^pass(?:es)?\b"
    r"|\bthis pass(?:es)?\b"
    r"|\bno\s+(?:issues?|errors?|violations?|problems?|findings?|spelling\s+errors?)\s+(?:were\s+)?found\b"
    r"|\bno issue\b"
    r"|\bexactly meets\b"
    r"|\bdeclared\b.{0,30}\bmatches\b.{0,30}\bcalculated\b"
    r"|\bmatches?\b.{0,30}\brequired\b"
    r"|\bvalues?\s+matches?\b",
    re.IGNORECASE | re.MULTILINE,
)

# pos_count and revision_check are handled entirely by Python — not sent to LLM
_LLM_CHECKS = ["spelling", "section_name", "parts_label", "drawing_title"]
_ALL_CHECKS = _LLM_CHECKS + ["pos_count", "revision_check", "drawing_status"]

_CHECK_PROMPTS: dict[str, str] = {k: get_check_prompt("spell", k) for k in _LLM_CHECKS}
_CHECK_META: dict[str, tuple[str, str, str]] = {k: get_check_meta("spell", k) for k in _ALL_CHECKS}

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
  not_found:   list of check keys where prerequisite drawing elements were absent

DEBUG NOTES — always populate one entry per active check, regardless of pass/fail:
  spelling:      "spelling: scanned=[<areas checked>] | misspellings=[<word: correction>,...] | overlap/truncated=[<locations>]"
  section_name:  "section_name: MARKERS=[<list from Ansicht/Bewehrung>] | VIEWS=[<list of Schnitt/Draufsicht titles>] | unmatched_markers=[...] | unmatched_views=[...]"
  parts_label:   "parts_label: EBT found=[<part codes>] | MT found=[<part codes>] | missing_label=[...] | wrong_label=[...]"
  drawing_title: "drawing_title: TITLE_DE=[<value or empty>] | TITLE_EN=[<value or empty>] | Drawing_No=[<value or empty>] | drawing_name=[<sheet header>] | lang_match=[PASS/FAIL] | name_match=[PASS/FAIL]"

RULES:
  • OUTPUT ONLY actual problems — items that clearly do not comply.
  • Do NOT output any item to describe a passing check or a verified-correct result.
  • An empty issues list means ALL enabled checks passed — that is the correct output when no problems exist.
  • Do NOT flag uncertain or marginally readable text.
  • If prerequisite drawing elements are absent, add the check key to not_found instead of skipping.\
"""


def _build_spell_task(enabled_sub: list[str] | None) -> str:
    active = [k for k in _LLM_CHECKS if enabled_sub is None or k in (enabled_sub or [])]
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
    check: str = Field(description="spelling | section_name | parts_label | drawing_title")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _SpellResult(BaseModel):
    issues: list[_SpellIssue]
    not_found: list[str] = Field(default_factory=list, description="Check keys where prerequisite drawing elements were absent")
    debug_notes: list[str] = Field(default_factory=list, description="One debug entry per active check showing extracted values")


def spell_check(state: GraphState) -> dict:
    pdf_content = state.get("pdf_content") or {}
    formatted: str = pdf_content.get("formatted") or ""
    title_block: dict = pdf_content.get("title_block") or {}
    enabled_sub = (state.get("enabled_sub_checks") or {}).get("spell")

    # ── pos_count: fully Python-based, no LLM ───────────────────────────────
    ts = str(title_block.get("letzte_stabstahlposition") or "").strip()
    ms = str(title_block.get("max_stabliste_pos") or "").strip()
    tm = str(title_block.get("letzte_mattenposition") or "").strip()
    mm = str(title_block.get("max_mattenliste_pos") or "").strip()
    print(f"[pos_count] TITLE_STAB={ts!r}  MAX_STAB={ms!r}  TITLE_MATTEN={tm!r}  MAX_MATTEN={mm!r}")

    # ── drawing_title: log pre-extracted values for debugging ────────────────
    dt_val = str(title_block.get("drawing_title_value") or "").strip()
    dn_val = str(title_block.get("drawing_no_value") or "").strip()
    dname  = str(title_block.get("drawing_name") or "").strip()
    print(f"[drawing_title] drawing_title_value={dt_val!r}  drawing_no_value={dn_val!r}  drawing_name={dname!r}")

    # ── revision_check: log pre-extracted values for debugging ───────────────
    rev_tb  = str(title_block.get("revision_title_block") or "").strip().upper()
    rev_tbl = str(title_block.get("revision_table_last") or "").strip().upper()
    print(f"[revision_check] TITLE_BLOCK={rev_tb!r}  TABLE_LAST={rev_tbl!r}")

    # ── drawing_status: log pre-extracted values for debugging ───────────────
    status_code  = str(title_block.get("status_title_block") or "").strip().upper()
    planfreigabe = str(title_block.get("planfreigabe_text") or "").strip()
    print(f"[drawing_status] STATUS={status_code!r}  PLANFREIGABE={planfreigabe!r}")
    if not status_code:
        print("[drawing_status] → NOT FOUND reason: status_title_block is empty")
    if not planfreigabe:
        print("[drawing_status] → NOT FOUND reason: planfreigabe_text is empty")

    # ── LLM call for the other spell checks ─────────────────────────────────
    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-6",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_SpellResult).with_retry(stop_after_attempt=2)

    human_content: list[dict] = [
        {
            "type": "text",
            "text": formatted,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": _build_spell_task(enabled_sub)},
    ]

    result: _SpellResult = llm.invoke(  # type: ignore[assignment]
        [
            SystemMessage(content=_COMMON_SYSTEM),
            HumanMessage(content=human_content),
        ],
        config={"callbacks": [_UsageCallback("spell_check")]},
    )
    print(f"[spell_check] raw items from LLM: {len(result.issues)}")
    for note in result.debug_notes:
        print(f"[debug][spell_check] {note}")

    by_check: dict[str, list[_SpellIssue]] = {k: [] for k in _CHECK_META}
    for item in result.issues:
        if item.confidence >= 0.60 and item.check in by_check and not _PASS_ITEM_RE.search(item.description):
            by_check[item.check].append(item)

    not_found_set = set(result.not_found or [])

    # ── pos_count Python comparison ──────────────────────────────────────────
    pos_enabled = enabled_sub is None or "pos_count" in (enabled_sub or [])
    if pos_enabled:
        if not ts and not tm:
            not_found_set.add("pos_count")
        else:
            if ts and ms and ts != ms:
                by_check["pos_count"].append(_SpellIssue(
                    check="pos_count", severity="error",
                    description=f"letzte Stabstahlposition: title block={ts}, Stabliste max={ms}",
                    page=1, location="title block", confidence=1.0,
                ))
            if tm and mm and tm != mm:
                by_check["pos_count"].append(_SpellIssue(
                    check="pos_count", severity="error",
                    description=f"letzte Mattenposition: title block={tm}, Mattenstahlliste max={mm}",
                    page=1, location="title block", confidence=1.0,
                ))

    # ── revision_check Python comparison ────────────────────────────────────
    rev_enabled = enabled_sub is None or "revision_check" in (enabled_sub or [])
    if rev_enabled:
        if not rev_tb or not rev_tbl:
            not_found_set.add("revision_check")
        elif rev_tb != rev_tbl:
            by_check["revision_check"].append(_SpellIssue(
                check="revision_check", severity="error",
                description=f"Revision mismatch: title block={rev_tb}, last revision in table={rev_tbl}",
                page=1, location="title block / revision history table", confidence=1.0,
            ))

    # ── drawing_status Python comparison ─────────────────────────────────────
    ds_enabled = enabled_sub is None or "drawing_status" in (enabled_sub or [])
    if ds_enabled:
        if not status_code or not planfreigabe:
            not_found_set.add("drawing_status")
        else:
            pf_upper = planfreigabe.upper()
            first = status_code[0]
            if first == "P":
                if "PRÜFUNG" not in pf_upper and "PRUFUNG" not in pf_upper:
                    by_check["drawing_status"].append(_SpellIssue(
                        check="drawing_status", severity="error",
                        description=f"Status={status_code} (Prüfung) but Planfreigabe shows: {planfreigabe!r}",
                        page=1, location="title block / Planfreigabe", confidence=1.0,
                    ))
            elif first in ("A", "F"):
                if "AUSFÜHRUNG" not in pf_upper and "AUSFUHRUNG" not in pf_upper:
                    by_check["drawing_status"].append(_SpellIssue(
                        check="drawing_status", severity="error",
                        description=f"Status={status_code} (Ausführung) but Planfreigabe shows: {planfreigabe!r}",
                        page=1, location="title block / Planfreigabe", confidence=1.0,
                    ))
            else:
                not_found_set.add("drawing_status")

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
        summary_desc = pass_desc if passed else (
            f"FAIL — {found[0].description}" if len(found) == 1
            else f"FAIL — {len(found)} issue(s) found."
        )
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
