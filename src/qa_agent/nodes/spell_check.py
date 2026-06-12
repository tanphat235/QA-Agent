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
    r"|\bvalues?\s+matches?\b"
    r"|\bno unmatched\b"
    r"|\bre-?evaluat"
    r"|\bcross-?check(?:ing)?\s+confirms\b"
    r"|\bafter\s+(?:full|complete)\s+review\b",
    re.IGNORECASE | re.MULTILINE,
)

# section_name checks only marker → view. View-without-marker items are false
# positives (marker labels are often unreadable in extracted text) — drop them.
_VIEW_TO_MARKER_RE = re.compile(
    r"\bview\b.{0,60}\bno\s+correspond\w*\b.{0,40}\bmarker\b",
    re.IGNORECASE,
)

# pos_count and revision_check are handled entirely by Python — not sent to LLM
_LLM_CHECKS = ["spelling", "section_name", "parts_label"]
_ALL_CHECKS = _LLM_CHECKS + ["pos_count", "revision_check", "drawing_status", "exposition_class", "steel_content", "lastausgleich", "overview_plan_check", "steel_list_check"]

# Expected concrete cover values per exposition class — BẢNG 3.1, φ10 default
# (Cmin,dur, ΔCdev, Cv)
_EXPOSITION_COVER: dict[str, tuple[int, int, int]] = {
    "XC1": (20, 10, 30),
    "XC2": (35, 15, 50),
    "XC3": (35, 15, 50),
    "XC4": (40, 15, 55),
}

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
  section_name:  "section_name: MARKERS=[<list from Ansicht/Bewehrung>] | VIEWS=[<list of Schnitt/Draufsicht titles>] | unmatched_markers=[...]"
  parts_label:   "parts_label: EBT found=[<part codes>] | MT found=[<part codes>] | missing_label=[...] | wrong_label=[...]"

RULES:
  • OUTPUT ONLY actual problems — items that clearly do not comply.
  • Do NOT output any item to describe a passing check or a verified-correct result.
  • Reason SILENTLY. The description field states only the violation itself — never your
    verification steps, re-evaluations, or lists of items that turned out to be correct.
    If re-checking resolves a suspected issue, omit the item entirely.
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
    check: str = Field(description="spelling | section_name | parts_label")
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

    # Holds dynamically computed pass messages (only used for steel_content currently)
    dynamic_pass_descs: dict[str, str] = {}

    # ── pos_count: fully Python-based, no LLM ───────────────────────────────
    ts = str(title_block.get("letzte_stabstahlposition") or "").strip()
    ms = str(title_block.get("max_stabliste_pos") or "").strip()
    tm = str(title_block.get("letzte_mattenposition") or "").strip()
    mm = str(title_block.get("max_mattenliste_pos") or "").strip()
    print(f"[pos_count] TITLE_STAB={ts!r}  MAX_STAB={ms!r}  TITLE_MATTEN={tm!r}  MAX_MATTEN={mm!r}")

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

    # ── exposition_class: log pre-extracted values ───────────────────────────
    xc_code      = str(title_block.get("exposition_class") or "").strip().upper()
    btd_cmin     = str(title_block.get("betondeckung_cmin_dur") or "").strip()
    btd_dc       = str(title_block.get("betondeckung_delta_c") or "").strip()
    btd_cv       = str(title_block.get("betondeckung_cv") or "").strip()
    print(f"[exposition_class] XC={xc_code!r}  cmin_dur={btd_cmin!r}  delta_c={btd_dc!r}  cv={btd_cv!r}")

    # ── steel_content: log pre-extracted values ──────────────────────────────
    mass_str = str(title_block.get("gesamtmasse") or "").strip()
    vol_str  = str(title_block.get("volumen") or "").strip()
    print(f"[steel_content] gesamtmasse={mass_str!r}  volumen={vol_str!r}")

    # ── lastausgleich: log pre-extracted values ───────────────────────────────
    la_ebt_found   = bool(title_block.get("rd_ebt_table_found"))
    la_rd_qty      = int(title_block.get("rd_ebt_max_qty") or 0)
    la_text_present = bool(title_block.get("lastausgleich_present"))

    # ── overview_plan_check: log pre-extracted values ─────────────────────────
    overview_plan_data: dict = state.get("overview_plan_data") or {}  # type: ignore[assignment]
    raw_text_main: str = pdf_content.get("raw_text") or ""
    op_vol_str    = str(title_block.get("volumen") or "").strip()
    op_wt_str     = str(title_block.get("gewicht") or "").strip()
    op_qty_str    = str(title_block.get("anzahl") or "").strip()
    op_drawing_no = str(title_block.get("drawing_no_value") or "").strip()
    op_title      = str(title_block.get("drawing_title_value") or "").strip()
    print(f"[overview_plan_check] vol={op_vol_str!r}  wt={op_wt_str!r}  qty={op_qty_str!r}  drawing_no={op_drawing_no!r}")
    print(f"[overview_plan_check] title={op_title[:60]!r}  rows={len(overview_plan_data.get('element_rows', []))}")
    print(f"[lastausgleich] ebt_table_found={la_ebt_found}  rd_max_qty={la_rd_qty}  text_present={la_text_present}")

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
        if item.confidence < 0.60 or item.check not in by_check or _PASS_ITEM_RE.search(item.description):
            continue
        if item.check == "section_name" and _VIEW_TO_MARKER_RE.search(item.description):
            print(f"[section_name] dropped view→marker item: {item.description[:80]!r}")
            continue
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

    # ── exposition_class Python comparison ───────────────────────────────────
    ec_enabled = enabled_sub is None or "exposition_class" in (enabled_sub or [])
    if ec_enabled:
        if not xc_code or xc_code not in _EXPOSITION_COVER:
            not_found_set.add("exposition_class")
            print(f"[exposition_class] NOT FOUND — xc_code={xc_code!r} not in lookup table")
        elif not btd_cmin and not btd_dc and not btd_cv:
            not_found_set.add("exposition_class")
            print("[exposition_class] NOT FOUND — all betondeckung values are empty")
        else:
            exp_cmin, exp_dc, exp_cv = _EXPOSITION_COVER[xc_code]

            def _safe_int(v: str) -> int | None:
                try:
                    return int(v)
                except (ValueError, TypeError):
                    return None

            act_cmin = _safe_int(btd_cmin)
            act_dc   = _safe_int(btd_dc)
            act_cv   = _safe_int(btd_cv)

            print(
                f"[exposition_class] {xc_code} | "
                f"Cmin,dur: actual={act_cmin} expected={exp_cmin} {'✓' if act_cmin == exp_cmin else '✗'} | "
                f"ΔCdev: actual={act_dc} expected={exp_dc} {'✓' if act_dc == exp_dc else '✗'} | "
                f"Cv: actual={act_cv} expected={exp_cv} {'✓' if act_cv == exp_cv else '✗'}"
            )

            if act_cmin is not None and act_cmin != exp_cmin:
                by_check["exposition_class"].append(_SpellIssue(
                    check="exposition_class", severity="error",
                    description=(
                        f"Cmin,dur mismatch for {xc_code}: "
                        f"drawing={act_cmin}, expected={exp_cmin} (Cnom φ10)"
                    ),
                    page=1, location="title block BETONDECKUNG", confidence=1.0,
                ))
            if act_dc is not None and act_dc != exp_dc:
                by_check["exposition_class"].append(_SpellIssue(
                    check="exposition_class", severity="error",
                    description=(
                        f"ΔCdev mismatch for {xc_code}: "
                        f"drawing={act_dc}, expected={exp_dc}"
                    ),
                    page=1, location="title block BETONDECKUNG", confidence=1.0,
                ))
            if act_cv is not None and act_cv != exp_cv:
                by_check["exposition_class"].append(_SpellIssue(
                    check="exposition_class", severity="error",
                    description=(
                        f"Cv mismatch for {xc_code}: "
                        f"drawing={act_cv}, expected={exp_cmin}+{exp_dc}={exp_cv}"
                    ),
                    page=1, location="title block BETONDECKUNG", confidence=1.0,
                ))

    # ── steel_content Python computation ────────────────────────────────────
    sc_enabled = enabled_sub is None or "steel_content" in (enabled_sub or [])
    if sc_enabled:
        if not mass_str or not vol_str:
            not_found_set.add("steel_content")
            print("[steel_content] NOT FOUND — mass or volume is empty")
        else:
            try:
                mass = float(mass_str.replace(",", "."))
                vol  = float(vol_str.replace(",", "."))
                if vol > 0:
                    ratio = mass / vol
                    dynamic_pass_descs["steel_content"] = (
                        f"PASS — Steel content: {mass:.2f} kg / {vol:.2f} m³ = {ratio:.1f} kg/m³"
                    )
                    print(f"[steel_content] {mass:.2f} / {vol:.2f} = {ratio:.1f} kg/m³")
                else:
                    not_found_set.add("steel_content")
                    print("[steel_content] NOT FOUND — volume is zero")
            except ValueError as exc:
                not_found_set.add("steel_content")
                print(f"[steel_content] NOT FOUND — parse error: {exc}")

    # ── lastausgleich Python check ────────────────────────────────────────────
    la_enabled = enabled_sub is None or "lastausgleich" in (enabled_sub or [])
    if la_enabled:
        if not la_ebt_found:
            not_found_set.add("lastausgleich")
            print("[lastausgleich] NOT FOUND — Einbauteilliste not in drawing")
        elif la_rd_qty >= 4:
            if not la_text_present:
                by_check["lastausgleich"].append(_SpellIssue(
                    check="lastausgleich", severity="error",
                    description=(
                        f"RD-type EBT (max Menge={la_rd_qty}) requires 'Lastausgleichgehänge' "
                        f"note in the drawing — not found"
                    ),
                    page=1, location="drawing / Einbauteilliste", confidence=1.0,
                ))
                print(f"[lastausgleich] FAIL — qty={la_rd_qty} >= 4 but Lastausgleichgehänge missing")
            else:
                print(f"[lastausgleich] PASS — qty={la_rd_qty} >= 4 and Lastausgleichgehänge present")
        else:  # la_rd_qty < 4 (includes 0 = no RD EBTs)
            if la_text_present:
                by_check["lastausgleich"].append(_SpellIssue(
                    check="lastausgleich", severity="error",
                    description=(
                        f"'Lastausgleichgehänge' note is present but RD-type EBT "
                        f"max Menge ({la_rd_qty}) is below 4 — note not required"
                    ),
                    page=1, location="drawing", confidence=1.0,
                ))
                print(f"[lastausgleich] FAIL — qty={la_rd_qty} < 4 but Lastausgleichgehänge present")
            else:
                print(f"[lastausgleich] PASS — qty={la_rd_qty} < 4 and Lastausgleichgehänge absent")

    # ── overview_plan_check: compare title block with overview plan table ──────
    op_enabled = enabled_sub is None or "overview_plan_check" in (enabled_sub or [])
    if op_enabled:
        if not overview_plan_data or not overview_plan_data.get("element_rows"):
            not_found_set.add("overview_plan_check")
            print("[overview_plan_check] NOT FOUND — no overview plan or table rows extracted")
        else:
            # Extract element code from drawing title (e.g. "Pr.- TT-Plate-202-850" → "202-850")
            # Fall back to scanning the raw text near the Bezeichnung / Drawing Title label.
            el_codes = re.findall(r"\d+[A-Z]{0,2}-\d+", op_title)
            if not el_codes:
                # Raw-text fallback: find element code in the title-block area
                title_area_m = re.search(
                    r"(?:Bezeichnung|Drawing Title)[^\n]*\n?(.*)",
                    raw_text_main, re.IGNORECASE | re.DOTALL,
                )
                if title_area_m:
                    # Only look in the first ~200 chars after the label
                    el_codes = re.findall(r"\d+[A-Z]{0,2}-\d+", title_area_m.group(1)[:200])
            element_code = el_codes[-1] if el_codes else None
            print(f"[overview_plan_check] element_code={element_code!r}  drawing_no={op_drawing_no!r}")

            # If drawing_no is still empty, extract from raw text directly
            if not op_drawing_no:
                dn_m = re.search(
                    r"(?:Drawing No|Plan-Nr)[^\n]*\n?\s*([A-Z]{2,}[A-Z0-9]*(?:-[A-Z0-9]+){4,})",
                    raw_text_main, re.IGNORECASE,
                )
                if not dn_m:
                    dn_m = re.search(r"\b([A-Z]{2,}[0-9]+(?:-[A-Z0-9]+){5,})\b", raw_text_main)
                if dn_m:
                    op_drawing_no = dn_m.group(1).strip().upper()
                    print(f"[overview_plan_check] drawing_no from raw_text fallback: {op_drawing_no!r}")

            # Find matching row: prefer Drawing No. match, fallback to element code match
            element_rows: list[dict] = overview_plan_data["element_rows"]
            matched: dict | None = None
            for row in element_rows:
                if op_drawing_no and row.get("drawing_no", "").upper() == op_drawing_no.upper():
                    matched = row
                    break
            if not matched and element_code:
                for row in element_rows:
                    if row.get("code", "").upper() == element_code.upper():
                        matched = row
                        break

            if not matched:
                not_found_set.add("overview_plan_check")
                print(f"[overview_plan_check] NOT FOUND — element {element_code!r}/{op_drawing_no!r} not in plan ({len(element_rows)} rows)")
            else:
                _TOL_PCT = 0.01  # 1 % relative tolerance

                plan_vol = matched.get("volume", "")
                plan_wt  = matched.get("weight",  "")
                plan_qty = matched.get("quantity", "")
                plan_dn  = matched.get("drawing_no", "")

                print(f"[overview_plan_check] ── Comparison ──────────────────────────────────")
                print(f"[overview_plan_check]   Volumen  : drawing={op_vol_str!r:12}  plan={plan_vol!r}")
                print(f"[overview_plan_check]   Gewicht  : drawing={op_wt_str!r:12}  plan={plan_wt!r}")
                print(f"[overview_plan_check]   Anzahl   : drawing={op_qty_str!r:12}  plan={plan_qty!r}")
                print(f"[overview_plan_check]   Drawing# : drawing={op_drawing_no!r}  plan={plan_dn!r}")
                print(f"[overview_plan_check] ────────────────────────────────────────────────")

                def _cmp_float(label: str, drawing_val: str, plan_val: str, unit: str) -> None:
                    if not drawing_val:
                        print(f"[overview_plan_check]   ERROR {label}: could not extract from drawing PDF")
                        by_check["overview_plan_check"].append(_SpellIssue(
                            check="overview_plan_check", severity="error",
                            description=f"{label}: could not extract value from drawing PDF (overview plan has {plan_val} {unit})",
                            page=1, location=f"title block {label}", confidence=1.0,
                        ))
                        return
                    if not plan_val:
                        print(f"[overview_plan_check]   SKIP {label}: plan value missing")
                        return
                    try:
                        d = float(drawing_val.replace(",", "."))
                        p = float(plan_val.replace(",", "."))
                        ref = max(abs(d), abs(p), 1e-9)
                        diff_pct = abs(d - p) / ref * 100
                        if diff_pct > _TOL_PCT * 100:
                            print(f"[overview_plan_check]   MISMATCH {label}: drawing={d} vs plan={p}  diff={diff_pct:.2f}%")
                            by_check["overview_plan_check"].append(_SpellIssue(
                                check="overview_plan_check", severity="error",
                                description=f"{label} mismatch: drawing={d} {unit}, overview plan={p} {unit} (diff {diff_pct:.2f}%)",
                                page=1, location=f"title block {label}", confidence=1.0,
                            ))
                        else:
                            print(f"[overview_plan_check]   OK {label}: drawing={d} vs plan={p}  diff={diff_pct:.2f}%")
                    except ValueError:
                        print(f"[overview_plan_check]   ERROR {label}: could not parse drawing={drawing_val!r} or plan={plan_val!r}")

                _cmp_float("Volumen", op_vol_str, plan_vol, "m³")
                _cmp_float("Gewicht", op_wt_str,  plan_wt,  "to")

                # Quantity: integer comparison
                if not op_qty_str:
                    print(f"[overview_plan_check]   ERROR Anzahl: could not extract from drawing PDF")
                    by_check["overview_plan_check"].append(_SpellIssue(
                        check="overview_plan_check", severity="error",
                        description=f"Anzahl: could not extract value from drawing PDF (overview plan has {plan_qty})",
                        page=1, location="title block Anzahl", confidence=1.0,
                    ))
                elif not plan_qty:
                    print(f"[overview_plan_check]   SKIP Anzahl: plan value missing")
                else:
                    try:
                        dq, pq = int(op_qty_str), int(plan_qty)
                        if dq != pq:
                            print(f"[overview_plan_check]   MISMATCH Anzahl: drawing={dq} vs plan={pq}")
                            by_check["overview_plan_check"].append(_SpellIssue(
                                check="overview_plan_check", severity="error",
                                description=f"Anzahl mismatch: drawing={dq}, overview plan={pq}",
                                page=1, location="title block Anzahl", confidence=1.0,
                            ))
                        else:
                            print(f"[overview_plan_check]   OK Anzahl: drawing={dq} vs plan={pq}")
                    except ValueError:
                        print(f"[overview_plan_check]   ERROR Anzahl: could not parse drawing={op_qty_str!r} or plan={plan_qty!r}")

                # Drawing No.: exact string match
                if not op_drawing_no:
                    print(f"[overview_plan_check]   SKIP Drawing#: drawing value not extracted")
                elif op_drawing_no.upper() != plan_dn.upper():
                    print(f"[overview_plan_check]   MISMATCH Drawing#: drawing={op_drawing_no!r} vs plan={plan_dn!r}")
                    by_check["overview_plan_check"].append(_SpellIssue(
                        check="overview_plan_check", severity="error",
                        description=f"Drawing No. mismatch: drawing={op_drawing_no!r}, overview plan={plan_dn!r}",
                        page=1, location="title block Drawing No.", confidence=1.0,
                    ))
                else:
                    print(f"[overview_plan_check]   OK Drawing#: {op_drawing_no!r}")

                n = len(by_check["overview_plan_check"])
                print(f"[overview_plan_check] {'PASS' if n == 0 else f'FAIL — {n} mismatch(es)'}")

    # ── steel_list_check ────────────────────────────────────────────────────
    sl_enabled = enabled_sub is None or "steel_list_check" in (enabled_sub or [])
    if sl_enabled:
        sl_data: dict = state.get("steel_list_data") or {}  # type: ignore[assignment]
        if not sl_data:
            not_found_set.add("steel_list_check")
            print("[steel_list_check] steel list not uploaded — skipping")
        else:
            pdf_c: dict = state.get("pdf_content") or {}  # type: ignore[assignment]
            dr_stab  = str(pdf_c.get("stabliste_total")       or "").strip()
            dr_matt  = str(pdf_c.get("mattenstahlliste_total") or "").strip()
            dr_ebt: list[dict] = pdf_c.get("einbauteilliste_items") or []

            sl_stab  = str(sl_data.get("stabliste_total")       or "").strip()
            sl_matt  = str(sl_data.get("mattenstahlliste_total") or "").strip()
            sl_ebt: list[dict] = sl_data.get("einbauteilliste_items") or []

            print(f"[steel_list_check] ── Comparison ──────────────────────────────────")
            print(f"[steel_list_check]   Stabliste Gesamtmasse   : drawing={dr_stab!r}  steel_list={sl_stab!r}")
            print(f"[steel_list_check]   Mattenstahl Gesamtgewicht: drawing={dr_matt!r}  steel_list={sl_matt!r}")
            print(f"[steel_list_check]   EBT items               : drawing={len(dr_ebt)}  steel_list={len(sl_ebt)}")
            print(f"[steel_list_check] ────────────────────────────────────────────────")

            _SL_TOL = 0.01  # 1% relative tolerance

            def _sl_cmp_float(label: str, dr_val: str, sl_val: str, unit: str = "kg") -> None:
                if not dr_val:
                    print(f"[steel_list_check]   ERROR {label}: could not extract from drawing PDF")
                    by_check["steel_list_check"].append(_SpellIssue(
                        check="steel_list_check", severity="error",
                        description=f"{label}: could not extract value from drawing PDF (steel list has {sl_val} {unit})",
                        page=1, location=f"drawing {label}", confidence=1.0,
                    ))
                    return
                if not sl_val:
                    print(f"[steel_list_check]   SKIP {label}: steel list value missing")
                    return
                try:
                    d, s = float(dr_val.replace(",", ".")), float(sl_val.replace(",", "."))
                    ref = max(abs(d), abs(s), 1e-9)
                    diff_pct = abs(d - s) / ref * 100
                    if diff_pct > _SL_TOL * 100:
                        print(f"[steel_list_check]   MISMATCH {label}: drawing={d} vs steel_list={s}  diff={diff_pct:.2f}%")
                        by_check["steel_list_check"].append(_SpellIssue(
                            check="steel_list_check", severity="error",
                            description=f"{label} mismatch: drawing={d} {unit}, steel list={s} {unit} (diff {diff_pct:.2f}%)",
                            page=1, location=f"drawing {label}", confidence=1.0,
                        ))
                    else:
                        print(f"[steel_list_check]   OK {label}: drawing={d} vs steel_list={s}  diff={diff_pct:.2f}%")
                except ValueError:
                    print(f"[steel_list_check]   ERROR {label}: parse error drawing={dr_val!r} sl={sl_val!r}")

            _sl_cmp_float("Stabliste Gesamtmasse",       dr_stab, sl_stab)
            _sl_cmp_float("Mattenstahlliste Gesamtgewicht", dr_matt, sl_matt)

            # EBT comparison — all 5 fields must match exactly
            dr_ebt_map = {item["ebt_nr"]: item for item in dr_ebt}
            sl_ebt_map = {item["ebt_nr"]: item for item in sl_ebt}

            _EBT_FIELDS = [
                ("hersteller",       "Hersteller"),
                ("bezeichnung",      "Bezeichnung"),
                ("korrosionsschutz", "Korrosionsschutz"),
                ("qty",              "Menge (Stück)"),
            ]

            for ebt_nr, dr_item in dr_ebt_map.items():
                if ebt_nr not in sl_ebt_map:
                    print(f"[steel_list_check]   MISSING in steel_list: EBT {ebt_nr}")
                    by_check["steel_list_check"].append(_SpellIssue(
                        check="steel_list_check", severity="error",
                        description=f"EBT {ebt_nr} ({dr_item.get('bezeichnung','')}) found in drawing but missing in steel list",
                        page=1, location="Einbauteilliste", confidence=1.0,
                    ))
                else:
                    sl_item = sl_ebt_map[ebt_nr]
                    mismatches = []
                    for field_key, field_label in _EBT_FIELDS:
                        dr_val = dr_item.get(field_key, "")
                        sl_val = sl_item.get(field_key, "")
                        if dr_val != sl_val:
                            mismatches.append(
                                f"{field_label}: drawing={dr_val!r} vs steel list={sl_val!r}"
                            )
                            print(
                                f"[steel_list_check]   MISMATCH EBT {ebt_nr} "
                                f"{field_label}: drawing={dr_val!r} vs steel_list={sl_val!r}"
                            )
                    if mismatches:
                        by_check["steel_list_check"].append(_SpellIssue(
                            check="steel_list_check", severity="error",
                            description=f"EBT {ebt_nr} field mismatch — " + "; ".join(mismatches),
                            page=1, location="Einbauteilliste", confidence=1.0,
                        ))
                    else:
                        print(f"[steel_list_check]   OK EBT {ebt_nr}")

            for ebt_nr in sl_ebt_map:
                if ebt_nr not in dr_ebt_map:
                    print(f"[steel_list_check]   EXTRA in steel_list: EBT {ebt_nr}")
                    by_check["steel_list_check"].append(_SpellIssue(
                        check="steel_list_check", severity="error",
                        description=f"EBT {ebt_nr} found in steel list but missing in drawing Einbauteilliste",
                        page=1, location="Einbauteilliste", confidence=1.0,
                    ))

            n_sl = len(by_check["steel_list_check"])
            print(f"[steel_list_check] {'PASS' if n_sl == 0 else f'FAIL — {n_sl} mismatch(es)'}")

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
        summary_desc = dynamic_pass_descs.get(check_key, pass_desc) if passed else (
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
