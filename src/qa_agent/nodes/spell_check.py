import logging
import re
from typing import NamedTuple

from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.outputs import LLMResult

from qa_agent.state import GraphState
from qa_agent.concrete_cover import expected_cover, governing_class, parse_classes
from qa_agent.drawing_language import (
    DrawingLanguage,
    detect_drawing_language,
    language_name,
)
from qa_agent.element_type import (
    display_name,
    element_name_candidates,
    normalize_element_type,
    steel_content_range,
)
from qa_agent.rag.retriever import get_check_prompt, get_check_meta, get_check_rebar_diameter
from qa_agent.nodes.issue_filter import OUTPUT_RULES, accept_finding, build_check_issues
from qa_agent.nodes.pdf_extractor import _normalize_ebt_nr, _ebt_field_matches, strip_name_codes
from qa_agent.nodes.user_ai_checks import run_user_ai_checks, _SYSTEM_VISION

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

_TASK_INTRO_VISION = """\
A precast wall structural drawing is attached as a rendered PDF document, followed by its
extracted text (supplementary cross-reference only). Inspect the rendered drawing and report
ONLY issues you can directly observe.\
"""

# Spelling false positives: LLM flags pdfplumber extraction noise as "garbled text".
_EXTRACTION_ARTIFACT_RE = re.compile(
    r"\b(?:garbled|corrupted)\b"
    r"|\bunreadable\s+text\s+strings?\b"
    r"|\boverlapping\s+text\s+fragments?\b"
    r"|\brotated/?vertical\s+labels?\b"
    r"|\bextract(?:ion)?\s+artifacts?\b",
    re.IGNORECASE,
)

# pos_count and revision_check are handled entirely by Python — not sent to LLM
_LLM_CHECKS = ["spelling", "section_name", "parts_label"]

# Checks that must read the rendered PDF. parts_label: labels drawn rotated or
# vertical in graphical views are dropped or fragmented by pdfplumber text
# extraction. section_name: judging whether a view draws the cut its marker
# defines needs the cut lines, the arrow directions and the view geometry, none
# of which survive text extraction.
# Run on Sonnet with the PDF attached; fall back to the text call without one.
_VISION_CHECKS = frozenset({"parts_label", "section_name"})
_ALL_CHECKS = _LLM_CHECKS + ["pos_count", "revision_check", "drawing_status", "exposition_class", "steel_content", "lastausgleich", "overview_plan_check", "steel_list_check"]

_LOC_TITLE_BLOCK = "title block"

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
  spelling:      "spelling: language=<language you judged the sheet to be in> | scanned=[<areas checked>] | misspellings=[<word: correction>,...] | foreign_language=[<quoted text: its language>,...] | overlap/truncated=[<locations>]"
  section_name:  "section_name: MARKERS=[<designation:orientation:viewed-from:position>,...] | VIEWS=[<designation:orientation drawn>,...] | matched=[...] | unmatched_markers=[...] | orphan_titles=[...] | misplaced=[<title: marker it really draws>,...]"
  parts_label:   "parts_label: EBT found=[<part codes>] | MT found=[<part codes>] | missing_label=[...] | wrong_label=[...]"

RULES:
  • OUTPUT ONLY actual problems — items that clearly do not comply.
  • Do NOT output any item to describe a passing check or a verified-correct result.
  • Do NOT flag uncertain or marginally readable text.
  • If prerequisite drawing elements are absent, add the check key to not_found instead of skipping.

""" + OUTPUT_RULES


def _build_spell_task(
    active: list[str], use_vision: bool = False, extra_context: str = "",
) -> str:
    check_keys = " | ".join(f'"{k}"' for k in active)
    blocks = "\n\n".join(_CHECK_PROMPTS[k] for k in active)
    intro = _TASK_INTRO_VISION if use_vision else _TASK_INTRO
    if extra_context:
        intro = intro + "\n\n" + extra_context
    return intro + "\n\n" + blocks + _TASK_OUTRO_TPL.format(check_keys=check_keys)


def _language_context(lang: DrawingLanguage) -> str:
    """The DRAWING LANGUAGE CONTEXT block the spelling prompt reads its step 1 from."""
    if lang.code == "unknown":
        return """\
DRAWING LANGUAGE CONTEXT
  Automatic detection found too little prose to name the sheet's language.
  Determine the primary language yourself from the title block labels, view
  titles and note text before applying the language-consistency rule.\
"""
    scores = ", ".join(f"{language_name(c)}={n}" for c, n in lang.scores.items())
    lines = [
        "DRAWING LANGUAGE CONTEXT",
        f"  Detected primary language: {lang.name}",
        f"  Marker-word hits: {scores}",
        f"  Read from: {', '.join(lang.markers[:15])}",
    ]
    if lang.secondary:
        lines.append(
            f"  A second language is also present in the extracted text: "
            f"{language_name(lang.secondary)} — locate that text and report it "
            f"under the language-consistency rule."
        )
    lines.append(
        "  Treat the detected language as the sheet's language unless the readable\n"
        "  text plainly contradicts it."
    )
    return "\n".join(lines)


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


def _run_spell_llm(
    keys: list[str],
    formatted: str,
    pdf_data: str | None,
    lang: DrawingLanguage | None = None,
) -> _SpellResult:
    """Run one group of LLM spell checks — text-only (Haiku) or vision (Sonnet + PDF)."""
    use_vision = bool(pdf_data)
    # Only the spelling check reads the language block; the other checks would
    # pay for the tokens without using them.
    context = _language_context(lang) if (lang and "spelling" in keys) else ""
    task = _build_spell_task(keys, use_vision=use_vision, extra_context=context)

    if use_vision:
        model = "claude-sonnet-4-6"
        system = _SYSTEM_VISION
        human_content: list[dict] = [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
                "cache_control": {"type": "ephemeral"},
            },
        ]
        if formatted:
            human_content.append({"type": "text", "text": formatted})
        human_content.append({"type": "text", "text": task})
    else:
        model = "claude-haiku-4-5"
        system = _COMMON_SYSTEM
        human_content = [
            {
                "type": "text",
                "text": formatted,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": task},
        ]

    label = f"spell_check_{'vision' if use_vision else 'text'}"
    print(f"[spell_check] {'vision' if use_vision else 'text'} group → {model}: {keys}")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model=model,  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_SpellResult).with_retry(stop_after_attempt=2)

    return llm.invoke(  # type: ignore[return-value]
        [SystemMessage(content=system), HumanMessage(content=human_content)],
        config={"callbacks": [_UsageCallback(label)]},
    )


# ── Element type from the drawing title (LLM) ────────────────────────────────
# The title block always names the element, but never cleanly: the name sits
# inside a German compound, next to project codes and axis labels, and shares a
# text line with whatever rebar callouts fall on the same y-band. Pattern
# matching on that has proven unreliable, so the model reads the name from a set
# of candidate lines and the plausible-range comparison below stays plain
# deterministic Python.

class _ElementTypeResult(BaseModel):
    element_type: str = Field(description="wall | column | beam | slab | unknown")
    evidence: str = Field(default="", description="The exact wording the type was read from")


_ELEMENT_TYPE_SYSTEM = """\
You identify which precast concrete element a drawing details, from text lines
taken off the sheet.

Answer with exactly one of:
  wall    — Wand, Wandplatte, Wandscheibe, Wandelement, wall panel
  column  — Stütze, Säule, Pfeiler, column, pillar
  beam    — Balken, Träger, Unterzug, Riegel, beam, girder
  slab    — Platte, Decke, Deckenplatte, Bodenplatte, Rippenplatte, TT-Plate,
            double-tee, slab
  unknown — no line names an element type

Worked examples:
  "Schalung und Bewehrung FT.- Wandplatte-Achse A-W503.1"      -> wall
  "20 44 ø 8 L=144cm Formwork and reinforcement Pr.- TT-Plate" -> slab
  "Bauteil : FT.-TT Platte Betonfestigkeit : C40/50"           -> slab

CRITICAL:
  • The lines are ordered most-trustworthy first. Prefer the drawing title and
    the Bauteil / Component field over any other mention.
  • A line may name an element belonging to a DIFFERENT drawing. Ignore mentions
    introduced by "Übersichtsplan" / "Overview plan" or a cross-reference to
    another sheet; classify the element this sheet details.
  • Lines are polluted with rebar callouts, dimensions, scales and part numbers
    ("4 ø 10 /5", "M 1:25", "03012"). Ignore that noise.
  • Any compound beginning with "Wand" is a wall: "Wandplatte" is a precast wall
    panel, NOT a slab, even though it ends in "-platte".
  • "TT-Plate" / "TT-Platte" / "TT Platte" is a double-tee floor slab.
  • Umlauts may be missing from the extracted text ("Stuetze", "Stutze",
    "Traeger"); treat those spellings as the same word.
  • Read only from the lines given. Never infer the element from project codes,
    drawing numbers or projects you recognise.
  • If no line names an element, answer "unknown". Never fall back to a default.
  • Put the exact wording you read the type from into "evidence".\
"""


def _classify_element_type(candidates: list[str]) -> tuple[str | None, str]:
    """Element type named in *candidates*, plus the wording it was read from.

    Returns (None, "") when no line names one or the call fails — the caller
    then has no range to compare against and reports NOT FOUND.
    """
    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-haiku-4-5",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=512,  # type: ignore[call-arg]
    ).with_structured_output(_ElementTypeResult).with_retry(stop_after_attempt=2)

    numbered = "\n".join(f"{i}. {line}" for i, line in enumerate(candidates, 1))
    try:
        result: _ElementTypeResult = llm.invoke(  # type: ignore[assignment]
            [
                SystemMessage(content=_ELEMENT_TYPE_SYSTEM),
                HumanMessage(content=f"Candidate lines from the sheet:\n{numbered}"),
            ],
            config={"callbacks": [_UsageCallback("element_type")]},
        )
    except Exception as exc:
        print(f"[steel_content] element type classification failed: {exc}")
        return None, ""

    return normalize_element_type(result.element_type), (result.evidence or "").strip()


# ── Gesamtmasse / Volumen fallback (LLM reads the rendered sheet) ────────────
# The deterministic readers anchor on label coordinates, and every drawing type
# lays its title block out differently: the value sits right of the label on one
# sheet, on the row below it on the next, in a cell of its own two columns over
# on a third. A layout the coordinate rules do not fit yields nothing, and the
# check then reports NOT FOUND on a sheet that plainly carries both numbers.
# When either value is missing, the model reads it off the rendered PDF — the
# ratio arithmetic and the range comparison stay in the Python above.

class _MassVolume(BaseModel):
    gesamtmasse: str = Field(default="", description="Stabliste Gesamtmasse / Gesamtgewicht in kg, digits only as printed; empty if not on the sheet")
    volumen: str = Field(default="", description="Title block Volumen in m³, digits only as printed; empty if not on the sheet")
    mass_location: str = Field(default="", description="Where the mass was read from")
    volume_location: str = Field(default="", description="Where the volume was read from")


_MASS_VOLUME_SYSTEM = """\
You read two numbers off a precast concrete drawing and nothing else.
Copy each value exactly as printed, digits only — no unit, no thousands
separator, no rounding. Return an empty string for a value that is not on the
sheet. Never calculate, estimate or infer a value, and never carry one over
from another drawing.\
"""

_MASS_VOLUME_PROMPT = """\
Read these two values off the attached drawing:

1. gesamtmasse — the TOTAL STEEL MASS in kg, printed as the closing total row of the
   Stabliste (bar schedule). Its label is "Gesamtmasse [kg]", "Gesamtgewicht [kg]" or
   the bilingual "Gesamtmasse / Total mass [kg]", and the value sits to the right of
   that label, often in a cell of its own at the far edge of the table.
   • If the sheet carries BOTH a Stabliste and a Mattenstahlliste, each with its own
     total, ADD the two totals and return the sum — the value wanted is the total
     steel on the sheet.
   • Do NOT return a Gesamtlänge, a per-row Masse, or a column header.

2. volumen — the CONCRETE VOLUME in m³ from the title block, labelled "Volumen" or
   "Volumen / Volume". The value is in that label's own cell: to the right of the
   label, or on the row directly below it. The unit m³ is printed beside it.
   • The neighbouring cells are Gewicht (weight in t) and Anzahl (a piece count).
     Do NOT return either of those. The volume is the value under the "Volumen"
     label and nothing else.

Put into mass_location and volume_location where you read each value from
(e.g. "Stabliste total row" / "title block Volumen cell"), so the read can be checked.
If a value is genuinely not printed anywhere on the sheet, return an empty string for
it — an empty value is handled; a wrong one is not.
"""


def _read_mass_volume_from_pdf(pdf_data: str | None) -> tuple[str, str]:
    """(gesamtmasse, volumen) read off the rendered drawing, or ("", "")."""
    if not pdf_data:
        print("[steel_content] no rendered PDF — cannot fall back to a visual read")
        return ("", "")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-6",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=1024,  # type: ignore[call-arg]
    ).with_structured_output(_MassVolume).with_retry(stop_after_attempt=2)

    try:
        result: _MassVolume = llm.invoke(  # type: ignore[assignment]
            [
                SystemMessage(content=_MASS_VOLUME_SYSTEM),
                HumanMessage(content=[
                    {
                        "type": "document",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": _MASS_VOLUME_PROMPT},
                ]),
            ],
            config={"callbacks": [_UsageCallback("mass_volume")]},
        )
    except Exception as exc:
        print(f"[steel_content] visual read failed: {exc}")
        return ("", "")

    mass = _clean_number(result.gesamtmasse)
    vol = _clean_number(result.volumen)
    print(
        f"[steel_content] visual read — gesamtmasse={mass!r} (from {result.mass_location[:50]!r})  "
        f"volumen={vol!r} (from {result.volume_location[:50]!r})"
    )
    return (mass, vol)


_CLEAN_NUM_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _clean_number(text: str) -> str:
    """The bare number in a value the model returned, decimal dot, or ""."""
    m = _CLEAN_NUM_RE.search((text or "").replace(" ", ""))
    return m.group(0).replace(",", ".") if m else ""


class _SteelContentOutcome(NamedTuple):
    not_found: bool
    issue: _SpellIssue | None
    pass_desc: str | None
    # What was missing, shown to the user in place of the generic NOT FOUND text.
    # "Volumen not found" is actionable; "NOT FOUND" alone is not.
    not_found_desc: str | None = None


def _evaluate_steel_content(
    mass_str: str, vol_str: str, candidates: list[str],
) -> _SteelContentOutcome:
    """Steel content ratio against the plausible band for the element on the sheet."""
    def _nf(reason: str) -> _SteelContentOutcome:
        print(f"[steel_content] NOT FOUND — {reason}")
        return _SteelContentOutcome(True, None, None, f"NOT FOUND — {reason}.")

    if not mass_str and not vol_str:
        return _nf(
            "neither the Stabliste Gesamtmasse nor the title block Volumen could be read"
        )
    if not mass_str:
        return _nf("Gesamtmasse not found in the Stabliste")
    if not vol_str:
        return _nf("Volumen not found in the title block")
    try:
        mass = float(mass_str.replace(",", "."))
        vol = float(vol_str.replace(",", "."))
    except ValueError:
        return _nf(f"Gesamtmasse {mass_str!r} or Volumen {vol_str!r} is not a number")
    if vol <= 0:
        return _nf(f"Volumen is {vol_str}, so no ratio can be formed")
    if not candidates:
        return _nf("no text on the sheet names the element this drawing details")

    element_type, evidence = _classify_element_type(candidates)
    print(
        f"[steel_content] element_type={element_type or '(unknown)'} "
        f"evidence={evidence[:60]!r} from {len(candidates)} candidate line(s)"
    )
    sc_range = steel_content_range(element_type)
    if sc_range is None:
        return _nf(
            "the drawing title names no element type with a known steel content range "
            f"(read {evidence[:60]!r})" if evidence
            else "the drawing title names no element type with a known steel content range"
        )

    ratio = mass / vol
    low, high = sc_range
    label = display_name(element_type)
    in_range = low <= ratio <= high
    print(
        f"[steel_content] {mass:.2f} / {vol:.2f} = {ratio:.1f} kg/m3 | "
        f"{label} range {low}-{high} {'OK' if in_range else 'OUT OF RANGE'}"
    )
    if in_range:
        return _SteelContentOutcome(False, None, (
            f"PASS — Steel content: {mass:.2f} kg / {vol:.2f} m³ = {ratio:.1f} kg/m³ "
            f"— within {label} range {low}–{high} kg/m³"
        ))
    return _SteelContentOutcome(False, _SpellIssue(
        check="steel_content", severity="error",
        description=(
            f"Steel content {ratio:.1f} kg/m³ ({mass:.2f} kg / {vol:.2f} m³) is outside "
            f"the {label} range {low}–{high} kg/m³"
        ),
        page=1, location=_LOC_TITLE_BLOCK, confidence=1.0,
    ), None)


# ── Steel-list Einbauteilliste extraction (LLM, column-aware) ────────────────
# pdfplumber gives a flat word/line stream; the previous regex/column-split
# parser repeatedly misaligned cells (the manufacturer name bled into the
# description, an entire row collapsed into one column, the quantity picked up
# the EBT number). That produced bogus "field mismatch" failures even when the
# drawing and the steel list carry identical tables. We let the model read the
# extracted text and place each value into its correct column instead — then the
# row-by-row / column-by-column comparison below is plain, deterministic Python.

class _EbtRow(BaseModel):
    ebt_nr: str = Field(description="EBT-Nummer / BIP-Number, exactly as printed")
    hersteller: str = Field(default="", description="Hersteller / Manufacturer column value only")
    bezeichnung: str = Field(default="", description="Bezeichnung / Description column value")
    korrosionsschutz: str = Field(default="", description="Korrosionsschutz column value; empty string if the cell is blank")
    qty: str = Field(default="", description="Menge (Stück) / Unit (Pcs) column value, the integer as printed")


class _EbtTables(BaseModel):
    drawing_found: bool = Field(description="true if an Einbauteilliste table is present in the DRAWING text")
    steel_list_found: bool = Field(description="true if an Einbauteilliste table is present in the STEEL LIST text")
    drawing_rows: list[_EbtRow] = Field(default_factory=list, description="DRAWING table rows, top-to-bottom")
    steel_list_rows: list[_EbtRow] = Field(default_factory=list, description="STEEL LIST table rows, top-to-bottom")


_EBT_EXTRACT_SYSTEM = """\
You are a precise table-extraction tool for German precast-concrete documents.
Read each table column by column from the rendered grid. Never translate,
normalize, reorder, infer, or invent any value — copy each cell exactly as
printed and place every value under its correct column header. Read every column
for every row, including narrow or mostly-empty columns. Apply the SAME column
logic identically to both documents.\
"""

_EBT_EXTRACT_PROMPT = """\
TASK — Extract the Einbauteilliste (Built-in / embedded parts list per precast element)
from BOTH inputs above and place every value under its correct column.

You are given two inputs, in this order:
  • DRAWING    — the structural drawing (first PDF document, or the text under "=== DRAWING TEXT ===")
  • STEEL LIST — the supplementary steel list (second PDF document, or the text under "=== STEEL LIST TEXT ===")

When PDF documents are supplied, READ THE TABLE DIRECTLY FROM THE RENDERED GRID —
that is the source of truth. Trace each column header straight down its column and
read the cell that lines up with each row's EBT-Nummer. (A flat text extraction can
drop a value or merge a narrow cell into its neighbour — do not rely on it.)

Each input contains a table whose title contains "Einbauteilliste" (also labelled
"Built-in parts list" / "je Fertigteil"). The columns, in fixed left-to-right order:

  1. EBT-Nummer / BIP-Number                  — the part number code
  2. Hersteller / Manufacturer                — the manufacturer name
  3. Bezeichnung / Description                — the product description text
  4. Korrosionsschutz / Corrosion protection — a SHORT code (e.g. FV) or blank
  5. Menge (Stück) / Unit (Pcs)               — the quantity, an integer

Return the rows of each table separately (drawing_rows / steel_list_rows),
one object per DATA row, top-to-bottom.

HOW TO READ THE KORROSIONSSCHUTZ COLUMN (the column that is most often mis-read):
  • It is the 4th column, between Bezeichnung and Menge. Its header may wrap across
    two lines (e.g. "Korrosionsschu / tz"). The cell holds a short code such as
    "FV" (feuerverzinkt), "feuerverzinkt", "verzinkt", "KTL", "blank", "keine".
  • This column is usually SPARSE — many rows are blank and only some rows carry a
    code. A code can sit far to the right of a long description with wide blank
    space before it; it STILL belongs to Korrosionsschutz.
  • A short code appearing after/at the end of the description text (e.g.
    "… JTA K38/17 L800   FV") is the Korrosionsschutz value — put it in
    `korrosionsschutz`, NEVER append it to `bezeichnung` and never read it as Menge.
  • Read this cell for EVERY row, in BOTH documents. Return an empty string ONLY
    when that cell is genuinely empty in the rendered grid.

STRICT RULES:
  • Copy every cell value EXACTLY as printed. Do not translate, abbreviate,
    reorder, round, normalize, or invent anything.
  • Bezeichnung: capture the description text only. If the manufacturer name is
    printed as the first word of the description, KEEP it in `bezeichnung` and also
    fill `hersteller`. Do NOT let any trailing Korrosionsschutz code leak into it.
  • `qty` is the Menge / Unit column only — never the EBT number or a dimension.
  • Skip header rows, section titles, project/metadata lines, subtotals and notes.
  • If a document has no Einbauteilliste table, set its *_found flag false and
    return an empty list for it.

FINAL CONSISTENCY RE-CHECK (do this before returning):
  The two tables describe the SAME parts. For every EBT-Nummer that appears in both
  drawing_rows and steel_list_rows, compare its Korrosionsschutz and its Menge.
  If they differ (e.g. one has "FV" and the other is empty), GO BACK and re-read
  that exact cell in the rendered grid of BOTH documents — you most likely under-read
  a sparse Korrosionsschutz cell. Correct it. Keep a difference only if, after
  re-reading both grids, the cells truly differ.
"""


def _extract_ebt_tables(
    drawing_text: str,
    steel_list_text: str,
    drawing_pdf: str | None = None,
    steel_list_pdf: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """LLM-extract both Einbauteilliste tables in one call, column-aligned and consistent.

    Prefers reading the rendered PDF documents (vision) so narrow/wrapped cells
    such as the Korrosionsschutz code are not lost; falls back to pdfplumber text.
    """
    def _to_rows(rows: list[_EbtRow]) -> list[dict]:
        return [
            {
                "ebt_nr":           _normalize_ebt_nr(r.ebt_nr),
                "hersteller":       (r.hersteller or "").strip(),
                "bezeichnung":      (r.bezeichnung or "").strip(),
                "korrosionsschutz": (r.korrosionsschutz or "").strip(),
                "qty":              (r.qty or "").strip(),
            }
            for r in rows
            if (r.ebt_nr or "").strip()
        ]

    use_vision = bool(drawing_pdf) and bool(steel_list_pdf)
    if not use_vision and not (drawing_text or "").strip() and not (steel_list_text or "").strip():
        print("[steel_list_check] no input to extract EBT tables from")
        return ([], [])

    def _doc(b64: str) -> dict:
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            "cache_control": {"type": "ephemeral"},
        }

    if use_vision:
        print("[steel_list_check] extracting EBT tables via rendered PDF documents (vision)")
        human_content: list[dict] = [
            {"type": "text", "text": "=== DRAWING (PDF document) ==="},
            _doc(drawing_pdf),  # type: ignore[arg-type]
            {"type": "text", "text": "=== STEEL LIST (PDF document) ==="},
            _doc(steel_list_pdf),  # type: ignore[arg-type]
            {"type": "text", "text": _EBT_EXTRACT_PROMPT},
        ]
    else:
        print("[steel_list_check] extracting EBT tables via pdfplumber text (no PDF available)")
        human_content = [
            {"type": "text", "text": "=== DRAWING TEXT ===\n" + (drawing_text or ""),
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "=== STEEL LIST TEXT ===\n" + (steel_list_text or "")},
            {"type": "text", "text": _EBT_EXTRACT_PROMPT},
        ]

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-6",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_EbtTables).with_retry(stop_after_attempt=2)

    result: _EbtTables = llm.invoke(  # type: ignore[assignment]
        [
            SystemMessage(content=_EBT_EXTRACT_SYSTEM),
            HumanMessage(content=human_content),
        ],
        config={"callbacks": [_UsageCallback("ebt_extract")]},
    )

    dr_rows = _to_rows(result.drawing_rows)
    sl_rows = _to_rows(result.steel_list_rows)
    print(f"[steel_list_check] LLM-extracted EBT rows — drawing={len(dr_rows)} (found={result.drawing_found})  "
          f"steel_list={len(sl_rows)} (found={result.steel_list_found})")
    for label, rows in (("drawing", dr_rows), ("steel list", sl_rows)):
        for it in rows:
            print(
                f"[steel_list_check]   [{label}] EBT {it['ebt_nr']}: "
                f"hersteller={it['hersteller']!r}  bezeichnung={it['bezeichnung'][:40]!r}  "
                f"ks={it['korrosionsschutz']!r}  qty={it['qty']!r}"
            )
    return (dr_rows, sl_rows)


# ── Stabliste / Mattenstahlliste rows (LLM read, Python compare) ─────────────
# The totals alone hide the defect that matters: both documents can sum to the
# same mass while a single position carries a different number, count, diameter
# or length. Both schedules are therefore read row by row from both documents
# and compared position by position by the plain Python below.

class _SteelRow(BaseModel):
    pos: str = Field(description="Pos. / Position column, exactly as printed")
    stck: str = Field(default="", description="Stck / Stück / quantity column")
    dia: str = Field(default="", description="Ø [mm] column on a bar row; the mesh type or Ø designation on a mesh row")
    einzel: str = Field(default="", description="Einzellänge [m] column")
    gesamt: str = Field(default="", description="Gesamtlänge [m] column")
    masse: str = Field(default="", description="Masse / Gewicht [kg] column")


class _SteelSchedules(BaseModel):
    drawing_bar_found: bool = Field(description="true if a Stabliste is present in the DRAWING")
    steel_list_bar_found: bool = Field(description="true if a Stabliste is present in the STEEL LIST")
    drawing_bar_rows: list[_SteelRow] = Field(default_factory=list, description="DRAWING Stabliste rows, top-to-bottom")
    steel_list_bar_rows: list[_SteelRow] = Field(default_factory=list, description="STEEL LIST Stabliste rows, top-to-bottom")
    drawing_mesh_found: bool = Field(description="true if a Mattenstahlliste is present in the DRAWING")
    steel_list_mesh_found: bool = Field(description="true if a Mattenstahlliste is present in the STEEL LIST")
    drawing_mesh_rows: list[_SteelRow] = Field(default_factory=list, description="DRAWING Mattenstahlliste rows, top-to-bottom")
    steel_list_mesh_rows: list[_SteelRow] = Field(default_factory=list, description="STEEL LIST Mattenstahlliste rows, top-to-bottom")


_SCHEDULE_EXTRACT_SYSTEM = """\
You are a precise table-extraction tool for German precast-concrete rebar schedules.
Read each table row by row from the rendered grid. Never translate, normalize,
reorder, round, infer or invent any value — copy each cell exactly as printed and
place every value under its correct column header. Return EVERY data row of every
table; a dropped row is a worse error than an uncertain one. Apply the SAME column
logic identically to both documents.\
"""

_SCHEDULE_EXTRACT_PROMPT = """\
TASK — Extract the rebar schedules from BOTH inputs above, row by row.

You are given two inputs, in this order:
  • DRAWING    — the structural drawing (first PDF document, or the text under "=== DRAWING TEXT ===")
  • STEEL LIST — the supplementary steel list (second PDF document, or the text under "=== STEEL LIST TEXT ===")

Two schedules are to be read from EACH input:
  • Stabliste — the bar schedule (also "Stabliste (1x)", "Stabliste - Biegeformen", bar list)
  • Mattenstahlliste — the mesh schedule (also mesh list, Matten, Mattenliste)

COLUMNS — the same six slots for both schedules, left to right:
  pos     Pos. / Position                — the position number, as printed
  stck    Stck / Stück / Anzahl / Pcs    — the piece count
  dia     Ø [mm]                         — the bar diameter; on a mesh row, the mesh
                                           type or Ø designation printed in that
                                           column (e.g. Q188A)
  einzel  Einzellänge [m] / Einzel Länge — the length of ONE piece
  gesamt  Gesamtlänge [m] / Gesamt Länge — the total length of the position
  masse   Masse [kg] / Gewicht [kg]      — the mass of the position

When PDF documents are supplied, READ EACH TABLE FROM THE RENDERED GRID — that is the
source of truth. Trace every column header straight down its column and read the cell
that lines up with each row's Pos. number.

READING THE STEEL LIST (the document that is most often mis-read):
  • The steel list draws a BENDING-SHAPE SKETCH for each position, between the Ø column
    and the length columns. The small numbers printed on that sketch are bending segment
    dimensions in cm (e.g. 112, 19, 76, 85) — they are NOT table columns. Ignore them
    completely. Read `einzel`, `gesamt` and `masse` from the numeric columns to the RIGHT
    of the sketch.
  • Rows continue across pages. Collect every row of a schedule from every page it spans.
  • The schedule may be grouped per element (e.g. "Summe ST-11"). Collect the data rows
    and skip the summary lines.

STRICT RULES:
  • Copy every cell EXACTLY as printed, including the decimal separator.
  • One object per DATA row. NEVER emit a row for a header, a section title, a bending
    sketch, a subtotal ("Summe …") or a total ("Gesamtmasse", "Gesamtgewicht",
    "Summe über alle Bauteile") — totals are compared separately.
  • Never merge two positions into one row and never split one position across two rows.
  • Leave a field as an empty string only when that cell is genuinely blank in the grid.
  • If a document has no Stabliste (or no Mattenstahlliste), set that *_found flag false
    and return an empty list for it. Do NOT substitute the other schedule's rows.

FINAL RE-CHECK (before returning):
  The two documents describe the SAME steel. Count the rows you read for each schedule on
  each side. If the counts differ, go back and re-read the grid of the shorter one — you
  most likely dropped a row that continues onto another page or sits beside a sketch.
  Report the rows you actually see; never pad a table to make the counts agree.
"""


def _extract_steel_schedules(
    drawing_text: str,
    steel_list_text: str,
    drawing_pdf: str | None = None,
    steel_list_pdf: str | None = None,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Read both rebar schedules from both documents in one call.

    Returns (drawing_bar, steel_list_bar, drawing_mesh, steel_list_mesh).
    Prefers the rendered PDF documents — pdfplumber interleaves the steel list's
    bending-sketch dimensions with the real columns — and falls back to text.
    """
    def _to_rows(rows: list[_SteelRow]) -> list[dict]:
        return [
            {
                "pos":    (r.pos or "").strip(),
                "stck":   (r.stck or "").strip(),
                "dia":    (r.dia or "").strip(),
                "einzel": (r.einzel or "").strip(),
                "gesamt": (r.gesamt or "").strip(),
                "masse":  (r.masse or "").strip(),
            }
            for r in rows
            if (r.pos or "").strip()
        ]

    use_vision = bool(drawing_pdf) and bool(steel_list_pdf)
    if not use_vision and not (drawing_text or "").strip() and not (steel_list_text or "").strip():
        print("[steel_list_check] no input to extract schedules from")
        return ([], [], [], [])

    def _doc(b64: str) -> dict:
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            "cache_control": {"type": "ephemeral"},
        }

    if use_vision:
        print("[steel_list_check] extracting schedules via rendered PDF documents (vision)")
        human_content: list[dict] = [
            {"type": "text", "text": "=== DRAWING (PDF document) ==="},
            _doc(drawing_pdf),  # type: ignore[arg-type]
            {"type": "text", "text": "=== STEEL LIST (PDF document) ==="},
            _doc(steel_list_pdf),  # type: ignore[arg-type]
            {"type": "text", "text": _SCHEDULE_EXTRACT_PROMPT},
        ]
    else:
        print("[steel_list_check] extracting schedules via pdfplumber text (no PDF available)")
        human_content = [
            {"type": "text", "text": "=== DRAWING TEXT ===\n" + (drawing_text or ""),
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "=== STEEL LIST TEXT ===\n" + (steel_list_text or "")},
            {"type": "text", "text": _SCHEDULE_EXTRACT_PROMPT},
        ]

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-6",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=8192,  # type: ignore[call-arg]
    ).with_structured_output(_SteelSchedules).with_retry(stop_after_attempt=2)

    result: _SteelSchedules = llm.invoke(  # type: ignore[assignment]
        [
            SystemMessage(content=_SCHEDULE_EXTRACT_SYSTEM),
            HumanMessage(content=human_content),
        ],
        config={"callbacks": [_UsageCallback("schedule_extract")]},
    )

    out = (
        _to_rows(result.drawing_bar_rows),
        _to_rows(result.steel_list_bar_rows),
        _to_rows(result.drawing_mesh_rows),
        _to_rows(result.steel_list_mesh_rows),
    )
    print(
        f"[steel_list_check] LLM-extracted rows — "
        f"Stabliste: drawing={len(out[0])} (found={result.drawing_bar_found}) "
        f"steel_list={len(out[1])} (found={result.steel_list_bar_found}) | "
        f"Mattenstahlliste: drawing={len(out[2])} (found={result.drawing_mesh_found}) "
        f"steel_list={len(out[3])} (found={result.steel_list_mesh_found})"
    )
    for label, rows in (
        ("drawing Stabliste", out[0]), ("steel list Stabliste", out[1]),
        ("drawing Mattenliste", out[2]), ("steel list Mattenliste", out[3]),
    ):
        for r in rows:
            print(
                f"[steel_list_check]   [{label}] Pos {r['pos']}: stck={r['stck']!r} "
                f"dia={r['dia']!r} einzel={r['einzel']!r} gesamt={r['gesamt']!r} masse={r['masse']!r}"
            )
    return out


# Every column of a schedule row except Pos, which is the key rows are matched on.
_SCHEDULE_FIELDS: list[tuple[str, str]] = [
    ("stck",   "Stück"),
    ("dia",    "Ø [mm]"),
    ("einzel", "Einzellänge [m]"),
    ("gesamt", "Gesamtlänge [m]"),
    ("masse",  "Masse [kg]"),
]

_NUM_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def _parse_schedule_num(text: str) -> float | None:
    """The number in a schedule cell, or None when the cell is not a plain number."""
    t = (text or "").strip().replace(" ", "")
    if not _NUM_RE.match(t):
        return None
    return float(t.replace(",", "."))


def _norm_pos(value: str) -> str:
    """Position key — printed as an integer, sometimes with a trailing dot."""
    return (value or "").strip().rstrip(".").lstrip("0") or "0"


def _schedule_value_matches(dr_val: str, sl_val: str) -> bool:
    """True when two schedule cells hold the same value.

    Numbers compare as numbers, so a decimal comma or a trailing zero ("3,50"
    against "3.5") is formatting, not a difference. Anything else compares as
    text, ignoring case and spacing. There is no tolerance here — a per-position
    value must agree exactly; only the schedule totals carry one.
    """
    d, s = (dr_val or "").strip(), (sl_val or "").strip()
    if d == s:
        return True
    dn, sn = _parse_schedule_num(d), _parse_schedule_num(s)
    if dn is not None and sn is not None:
        return abs(dn - sn) < 1e-9
    return d.replace(" ", "").lower() == s.replace(" ", "").lower()


def _row_summary(row: dict) -> str:
    """Short "4 × Ø14, 3.27 m, 15.83 kg" description of a schedule row."""
    bits = []
    if row.get("stck") and row.get("dia"):
        bits.append(f"{row['stck']} × Ø{row['dia']}")
    elif row.get("dia"):
        bits.append(f"Ø{row['dia']}")
    if row.get("einzel"):
        bits.append(f"{row['einzel']} m")
    if row.get("masse"):
        bits.append(f"{row['masse']} kg")
    return ", ".join(bits)


def _index_by_pos(rows: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """Map rows by normalized Pos, plus the positions that occur more than once."""
    by_pos: dict[str, dict] = {}
    dups: list[str] = []
    for row in rows:
        key = _norm_pos(row.get("pos", ""))
        if not key:
            continue
        if key in by_pos:
            if key not in dups:
                dups.append(key)
            continue
        by_pos[key] = row
    return by_pos, dups


def _compare_schedule(
    label: str, dr_rows: list[dict], sl_rows: list[dict],
) -> list[_SpellIssue]:
    """Compare one schedule position by position — one issue per difference.

    Identical logic serves the Stabliste and the Mattenstahlliste; only the label
    carried into the descriptions differs.
    """
    def _issue(desc: str) -> _SpellIssue:
        return _SpellIssue(
            check="steel_list_check", severity="error", description=desc,
            page=1, location=label, confidence=1.0,
        )

    found: list[_SpellIssue] = []
    dr_map, dr_dups = _index_by_pos(dr_rows)
    sl_map, sl_dups = _index_by_pos(sl_rows)

    for side, dups in (("drawing", dr_dups), ("steel list", sl_dups)):
        for pos in dups:
            print(f"[steel_list_check]   DUPLICATE {label} Pos {pos} in {side}")
            found.append(_issue(f"{label}: Pos {pos} appears more than once in the {side}"))

    missing = [p for p in dr_map if p not in sl_map]
    extra   = [p for p in sl_map if p not in dr_map]

    # A position renumbered between the two documents surfaces as one missing and
    # one extra row holding identical values. That is one defect, not two — pair
    # them up and report the renumbering itself.
    for dp in list(missing):
        for sp in list(extra):
            if all(
                _schedule_value_matches(dr_map[dp].get(k, ""), sl_map[sp].get(k, ""))
                for k, _ in _SCHEDULE_FIELDS
            ):
                missing.remove(dp)
                extra.remove(sp)
                print(f"[steel_list_check]   RENUMBERED {label}: drawing Pos {dp} = steel list Pos {sp}")
                found.append(_issue(
                    f"{label}: Pos {dp} in the drawing is Pos {sp} in the steel list "
                    f"— same {_row_summary(dr_map[dp])}, different position number"
                ))
                break

    for pos in missing:
        print(f"[steel_list_check]   MISSING in steel list: {label} Pos {pos}")
        found.append(_issue(
            f"{label}: Pos {pos} ({_row_summary(dr_map[pos])}) is in the drawing "
            f"but missing from the steel list"
        ))
    for pos in extra:
        print(f"[steel_list_check]   EXTRA in steel list: {label} Pos {pos}")
        found.append(_issue(
            f"{label}: Pos {pos} ({_row_summary(sl_map[pos])}) is in the steel list "
            f"but missing from the drawing"
        ))

    for pos, dr_row in dr_map.items():
        sl_row = sl_map.get(pos)
        if sl_row is None:
            continue
        diffs = [
            f"{field_label}: drawing={dr_row.get(key, '')!r} vs steel list={sl_row.get(key, '')!r}"
            for key, field_label in _SCHEDULE_FIELDS
            if not _schedule_value_matches(dr_row.get(key, ""), sl_row.get(key, ""))
        ]
        if diffs:
            print(f"[steel_list_check]   MISMATCH {label} Pos {pos}: " + "; ".join(diffs))
            found.append(_issue(f"{label}: Pos {pos} mismatch — " + "; ".join(diffs)))
        else:
            print(f"[steel_list_check]   OK {label} Pos {pos}")

    return found


# ── Overview plan lookup by element code ─────────────────────────────────────
# Sheets in these projects carry their element code in the top-left corner
# ("ST-11-01"). That code also names the element on the overview plan, in two
# places at once: a row of the element table, and a callout block drawn beside
# the element on the plan itself ("ST-11-01 / Stat. Pos. ST-11 / bxh= 50x50cm /
# Gewicht= 7.79 T"). parse_overview_elements() reads both off the plan's word
# coordinates; the comparison below is plain Python over what it found.

def _compare_overview_element(
    code: str, plan: dict, drawing: dict,
) -> list[_SpellIssue]:
    """Drawing title block against what the overview plan states for *code*.

    A field the plan does not state is SKIPPED, not failed. Overview plans in
    these projects carry no Volumen column at all, and a column the plan simply
    does not have is not a defect in the drawing.
    """
    def _issue(desc: str, where: str) -> _SpellIssue:
        return _SpellIssue(
            check="overview_plan_check", severity="error", description=desc,
            page=1, location=f"title block {where}", confidence=1.0,
        )

    found: list[_SpellIssue] = []
    _TOL_PCT = 1.0  # % — the same band the drawing-number table comparison uses

    for plan_key, dr_key, label, unit in (
        ("volume",   "volumen", "Volumen", "m³"),
        ("weight",   "gewicht", "Gewicht", "t"),
        ("quantity", "anzahl",  "Anzahl",  ""),
    ):
        plan_val = str(plan.get(plan_key) or "").strip()
        dr_val = str(drawing.get(dr_key) or "").strip()
        if not plan_val:
            print(f"[overview_plan_check]   SKIP {label}: the overview plan does not state it for {code}")
            continue
        if not dr_val:
            print(f"[overview_plan_check]   ERROR {label}: not read from the drawing")
            found.append(_issue(
                f"{label}: could not read the value from the drawing "
                f"(overview plan states {plan_val} {unit}".rstrip() + f" for {code})",
                label,
            ))
            continue
        d, pv = _parse_schedule_num(dr_val), _parse_schedule_num(plan_val)
        if d is None or pv is None:
            print(f"[overview_plan_check]   ERROR {label}: cannot parse drawing={dr_val!r} plan={plan_val!r}")
            continue
        diff_pct = abs(d - pv) / max(abs(d), abs(pv), 1e-9) * 100
        if diff_pct > _TOL_PCT:
            print(f"[overview_plan_check]   MISMATCH {label}: drawing={d} vs plan={pv} ({diff_pct:.2f}%)")
            found.append(_issue(
                f"{label} mismatch for {code}: drawing={dr_val} {unit}".rstrip()
                + f", overview plan={plan_val} {unit}".rstrip()
                + f" (diff {diff_pct:.2f}%)",
                label,
            ))
        else:
            print(f"[overview_plan_check]   OK {label}: drawing={d} vs plan={pv}")

    # Codes compare as text, exactly. The sheet appends its revision and status
    # to its own name ("…-FT-050-B-F") while the plan lists it without them.
    for plan_key, dr_key, label, strip_codes in (
        ("stat_pos",   "statische_position", "Statische Positionsnummer", False),
        ("drawing_no", "plan_id",            "Drawing No.",               True),
    ):
        plan_val = str(plan.get(plan_key) or "").strip()
        dr_val = str(drawing.get(dr_key) or "").strip()
        if strip_codes:
            dr_val = strip_name_codes(dr_val)
        if not plan_val:
            print(f"[overview_plan_check]   SKIP {label}: the overview plan does not state it for {code}")
            continue
        if not dr_val:
            print(f"[overview_plan_check]   SKIP {label}: not read from the drawing")
            continue
        if dr_val.upper().replace(" ", "") != plan_val.upper().replace(" ", ""):
            print(f"[overview_plan_check]   MISMATCH {label}: drawing={dr_val!r} vs plan={plan_val!r}")
            found.append(_issue(
                f"{label} mismatch for {code}: drawing={dr_val}, overview plan={plan_val}",
                label,
            ))
        else:
            print(f"[overview_plan_check]   OK {label}: {dr_val!r}")

    return found



def spell_check(state: GraphState) -> dict:
    pdf_content = state.get("pdf_content") or {}
    formatted: str = pdf_content.get("formatted") or ""
    title_block: dict = pdf_content.get("title_block") or {}
    enabled_sub = (state.get("enabled_sub_checks") or {}).get("spell")

    # Holds dynamically computed pass messages (steel_content range, spelling language)
    dynamic_pass_descs: dict[str, str] = {}
    # Replaces a check's generic NOT FOUND text with what was actually missing.
    dynamic_not_found_descs: dict[str, str] = {}

    # ── pos_count: fully Python-based, no LLM ───────────────────────────────
    ts = str(title_block.get("letzte_stabstahlposition") or "").strip()
    ms = str(title_block.get("max_stabliste_pos") or "").strip()
    tm = str(title_block.get("letzte_mattenposition") or "").strip()
    mm = str(title_block.get("max_mattenliste_pos") or "").strip()
    print(f"[pos_count] TITLE_STAB={ts!r}  MAX_STAB={ms!r}  TITLE_MATTEN={tm!r}  MAX_MATTEN={mm!r}")

    # ── revision / status codes: title block field, else the drawing name ────
    # Title block layouts differ per drawing type and many carry no Revision or
    # Status field. Those sheets state both codes at the end of their name
    # ("…-FT-050-B-F" → revision B, status F), so the name is the fallback
    # source — and, when a sheet has both, the cross-check between them.
    plan_id      = str(title_block.get("plan_id") or "").strip()
    rev_name     = str(title_block.get("revision_plan_id") or "").strip().upper()
    status_name  = str(title_block.get("status_plan_id") or "").strip().upper()

    rev_field = str(title_block.get("revision_title_block") or "").strip().upper()
    rev_tbl   = str(title_block.get("revision_table_last") or "").strip().upper()
    rev_tb    = rev_field or rev_name
    print(
        f"[revision_check] FIELD={rev_field!r}  NAME={rev_name!r}  "
        f"EFFECTIVE={rev_tb!r}  TABLE_LAST={rev_tbl!r}  plan_id={plan_id!r}"
    )
    if not rev_field and rev_name:
        print(f"[revision_check] revision read from the drawing name {plan_id!r}")

    status_field = str(title_block.get("status_title_block") or "").strip().upper()
    status_code  = status_field or status_name
    planfreigabe = str(title_block.get("planfreigabe_text") or "").strip()
    print(
        f"[drawing_status] FIELD={status_field!r}  NAME={status_name!r}  "
        f"EFFECTIVE={status_code!r}  PLANFREIGABE={planfreigabe!r}"
    )
    if not status_field and status_name:
        print(f"[drawing_status] status read from the drawing name {plan_id!r}")
    if not status_code:
        print("[drawing_status] → NOT FOUND reason: no status code in the title block or the drawing name")
    if not planfreigabe:
        print("[drawing_status] → NOT FOUND reason: planfreigabe_text is empty")

    # ── exposition_class: log pre-extracted values ───────────────────────────
    ec_classes   = [str(c).upper() for c in (title_block.get("exposition_classes") or []) if c]
    if not ec_classes:
        ec_classes = parse_classes(str(title_block.get("exposition_class") or ""))
    xc_code      = ", ".join(ec_classes)
    btd_cmin     = str(title_block.get("betondeckung_cmin_dur") or "").strip()
    btd_dc       = str(title_block.get("betondeckung_delta_c") or "").strip()
    btd_cv       = str(title_block.get("betondeckung_cv") or "").strip()
    print(f"[exposition_class] XC={xc_code!r}  cmin_dur={btd_cmin!r}  delta_c={btd_dc!r}  cv={btd_cv!r}")

    # ── steel_content: log pre-extracted values ──────────────────────────────
    mass_str = str(title_block.get("gesamtmasse") or "").strip()
    vol_str  = str(title_block.get("volumen") or "").strip()
    # The plausible ratio band depends on which element the sheet details, so
    # collect every line that might name it — drawing_title_value alone is not
    # enough, as the title-block label often extracts without its value.
    sc_candidates = element_name_candidates(
        str(pdf_content.get("raw_text") or ""),
        title_block.get("drawing_title_value"),
        title_block.get("drawing_name"),
    )
    print(
        f"[steel_content] gesamtmasse={mass_str!r}  volumen={vol_str!r}  "
        f"element_name_candidates={len(sc_candidates)}"
    )

    # ── lastausgleich: log pre-extracted values ───────────────────────────────
    la_ebt_found   = bool(title_block.get("rd_ebt_table_found"))
    la_anchor_qty  = int(title_block.get("rd_ebt_max_qty") or 0)
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
    print(f"[lastausgleich] ebt_table_found={la_ebt_found}  anchor_max_qty={la_anchor_qty}  text_present={la_text_present}")

    # ── LLM calls for the other spell checks ─────────────────────────────────
    # Text checks run on Haiku with extracted text. Vision checks (parts_label)
    # must read labels drawn in graphical views, so they run on Sonnet with the
    # rendered PDF attached — pdfplumber drops/fragments rotated view labels.
    active_llm = [k for k in _LLM_CHECKS if enabled_sub is None or k in (enabled_sub or [])]
    pdf_data: str | None = state.get("pdf_data")  # type: ignore[assignment]

    # ── spelling: which language is the sheet written in? ────────────────────
    # Detected here in Python so the answer is the same on every run, then handed
    # to the model — it decides nothing about the language, it only locates text
    # that does not belong to it. Detect on raw_text, never on `formatted`: the
    # formatter's own English section headers would count toward English.
    lang = detect_drawing_language(str(pdf_content.get("raw_text") or ""))
    print(
        f"[spelling] language={lang.code} ({lang.name})  confidence={lang.confidence:.2f}  "
        f"scores={lang.scores}  secondary={lang.secondary or '-'}"
    )
    print(f"[spelling] language markers={lang.markers[:15]}")
    if lang.code != "unknown":
        dynamic_pass_descs["spelling"] = (
            f"PASS — no spelling or language errors found "
            f"(drawing language: {lang.name})."
        )

    vision_keys = [k for k in active_llm if k in _VISION_CHECKS] if pdf_data else []
    text_keys = [k for k in active_llm if k not in vision_keys]
    if not pdf_data and any(k in _VISION_CHECKS for k in active_llm):
        print(
            f"[spell_check] WARNING: {sorted(_VISION_CHECKS & set(active_llm))} need the rendered "
            f"PDF but pdf_data is absent — falling back to text-only extraction"
        )

    results: list[_SpellResult] = []
    if text_keys:
        results.append(_run_spell_llm(text_keys, formatted, None, lang))
    if vision_keys:
        results.append(_run_spell_llm(vision_keys, formatted, pdf_data, lang))

    by_check: dict[str, list[_SpellIssue]] = {k: [] for k in _CHECK_META}
    not_found_set: set[str] = set()
    for result in results:
        print(f"[spell_check] raw items from LLM: {len(result.issues)}")
        for note in result.debug_notes:
            print(f"[debug][spell_check] {note}")
        not_found_set |= set(result.not_found or [])
        for item in result.issues:
            if item.check not in by_check:
                continue
            if not accept_finding(item.description, item.confidence):
                print(f"[{item.check}] dropped non-violation item: {item.description[:100]!r}")
                continue
            if item.check == "spelling" and _EXTRACTION_ARTIFACT_RE.search(item.description):
                print(f"[spelling] dropped extraction-artifact item: {item.description[:100]!r}")
                continue
            by_check[item.check].append(item)

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
                    page=1, location=_LOC_TITLE_BLOCK, confidence=1.0,
                ))
            if tm and mm and tm != mm:
                by_check["pos_count"].append(_SpellIssue(
                    check="pos_count", severity="error",
                    description=f"letzte Mattenposition: title block={tm}, Mattenstahlliste max={mm}",
                    page=1, location=_LOC_TITLE_BLOCK, confidence=1.0,
                ))

    # ── revision_check Python comparison ────────────────────────────────────
    rev_enabled = enabled_sub is None or "revision_check" in (enabled_sub or [])
    if rev_enabled:
        # Two independent comparisons, whichever the sheet supports: the revision
        # against the revision history table, and the Revision field against the
        # code carried in the drawing name. NOT FOUND only when neither can run.
        rev_compared = False
        if rev_tb and rev_tbl:
            rev_compared = True
            if rev_tb != rev_tbl:
                src = (
                    f"the title block states {rev_tb}" if rev_field
                    else f"the drawing name {plan_id} ends in {rev_tb}"
                )
                by_check["revision_check"].append(_SpellIssue(
                    check="revision_check", severity="error",
                    description=(
                        f"Revision mismatch: {src}, but the newest row of the revision "
                        f"history table is {rev_tbl}"
                    ),
                    page=1, location="title block / revision history table", confidence=1.0,
                ))
        if rev_field and rev_name:
            rev_compared = True
            if rev_field != rev_name:
                by_check["revision_check"].append(_SpellIssue(
                    check="revision_check", severity="error",
                    description=(
                        f"Revision mismatch: title block Revision field={rev_field}, "
                        f"drawing name {plan_id} ends in {rev_name}"
                    ),
                    page=1, location="title block / drawing name", confidence=1.0,
                ))
        if not rev_compared:
            if rev_tb:
                # The sheet states its revision in exactly one place and nothing
                # contradicts it. That is a pass, not a NOT FOUND: most sheets of
                # this kind carry no revision history table at all, and reporting
                # every one of them as unreadable buries the real findings.
                src = "title block" if rev_field else f"drawing name {plan_id}"
                dynamic_pass_descs["revision_check"] = (
                    f"PASS — Revision {rev_tb}, read from the {src}. "
                    f"The sheet states it in one place only, so there is nothing to compare it against."
                )
                print(f"[revision_check] PASS — revision {rev_tb!r} from {src}, single source")
            else:
                not_found_set.add("revision_check")
                print(
                    f"[revision_check] NOT FOUND — no revision code anywhere "
                    f"(field={rev_field!r} name={rev_name!r} table={rev_tbl!r})"
                )

    # ── drawing_status Python comparison ─────────────────────────────────────
    ds_enabled = enabled_sub is None or "drawing_status" in (enabled_sub or [])
    if ds_enabled:
        # This check compares the status code against the Planfreigabe approval
        # text and nothing else. The code is read from the title block Status
        # field, or from the end of the drawing name when the sheet has no such
        # field, but the two are never played off against each other — that is
        # not what this check is for.
        status_compared = False

        if status_code and planfreigabe:
            pf_upper = planfreigabe.upper()
            first = status_code[0]
            src = "title block" if status_field else f"drawing name {plan_id}"
            if first == "P":
                status_compared = True
                if "PRÜFUNG" not in pf_upper and "PRUFUNG" not in pf_upper:
                    by_check["drawing_status"].append(_SpellIssue(
                        check="drawing_status", severity="error",
                        description=f"Status={status_code} (Prüfung, from {src}) but Planfreigabe shows: {planfreigabe!r}",
                        page=1, location="title block / Planfreigabe", confidence=1.0,
                    ))
            elif first in ("A", "F"):
                status_compared = True
                if "AUSFÜHRUNG" not in pf_upper and "AUSFUHRUNG" not in pf_upper:
                    by_check["drawing_status"].append(_SpellIssue(
                        check="drawing_status", severity="error",
                        description=f"Status={status_code} (Ausführung, from {src}) but Planfreigabe shows: {planfreigabe!r}",
                        page=1, location="title block / Planfreigabe", confidence=1.0,
                    ))
            else:
                print(f"[drawing_status] status prefix {first!r} is not P / A / F — no Planfreigabe rule applies")

        if not status_compared:
            if status_code:
                src = "title block" if status_field else f"drawing name {plan_id}"
                why = (
                    "the sheet carries no Planfreigabe text to compare it against"
                    if not planfreigabe
                    else f"its first letter {status_code[0]!r} is not P, A or F, so no Planfreigabe rule applies"
                )
                dynamic_pass_descs["drawing_status"] = (
                    f"PASS — Status {status_code}, read from the {src}; {why}."
                )
                print(f"[drawing_status] PASS — status {status_code!r} from {src}; {why}")
            else:
                not_found_set.add("drawing_status")
                print(
                    f"[drawing_status] NOT FOUND — no status code anywhere "
                    f"(field={status_field!r} name={status_name!r})"
                )

    # ── exposition_class Python comparison ───────────────────────────────────
    ec_enabled = enabled_sub is None or "exposition_class" in (enabled_sub or [])
    if ec_enabled:
        # Which Table 3.1 c_nom column to compare against — Ø10 unless the user
        # picked another diameter in Define Rules.
        ec_diameter = get_check_rebar_diameter("spell", "exposition_class")
        # A drawing names several classes ("XC1, XD1") and must satisfy all of
        # them, so the comparison is made against the one demanding the most
        # cover — a chloride class outranks a carbonation class, and meeting it
        # meets the others too.
        ec_governing = governing_class(ec_classes, ec_diameter)
        expected = expected_cover(ec_governing or "", ec_diameter)
        if len(ec_classes) > 1:
            print(
                f"[exposition_class] classes on the drawing={ec_classes} → "
                f"{ec_governing} governs at Ø{ec_diameter}"
            )
        if expected is None:
            not_found_set.add("exposition_class")
            print(
                f"[exposition_class] NOT FOUND — no cover table entry for "
                f"{ec_classes or '(no class read)'} at Ø{ec_diameter}"
            )
        elif not btd_cmin and not btd_dc and not btd_cv:
            not_found_set.add("exposition_class")
            print("[exposition_class] NOT FOUND — all betondeckung values are empty")
        else:
            exp_cmin, exp_dc, exp_cv = expected

            def _safe_int(v: str) -> int | None:
                try:
                    return int(v)
                except (ValueError, TypeError):
                    return None

            act_cmin = _safe_int(btd_cmin)
            act_dc   = _safe_int(btd_dc)
            act_cv   = _safe_int(btd_cv)

            others = [c for c in ec_classes if c != ec_governing]
            governs = (
                f"{ec_governing} (governing; drawing also names {', '.join(others)})"
                if others else f"{ec_governing}"
            )
            print(
                f"[exposition_class] {governs} @ Ø{ec_diameter} | "
                f"Cmin,dur: actual={act_cmin} expected={exp_cmin} {'✓' if act_cmin == exp_cmin else '✗'} | "
                f"ΔCdev: actual={act_dc} expected={exp_dc} {'✓' if act_dc == exp_dc else '✗'} | "
                f"Cv: actual={act_cv} expected={exp_cv} {'✓' if act_cv == exp_cv else '✗'}"
            )
            dynamic_pass_descs["exposition_class"] = (
                f"PASS — {governs} at Ø{ec_diameter}: Cmin,dur={exp_cmin}, "
                f"ΔCdev={exp_dc}, Cv={exp_cv} (Table 3.1)"
            )

            if act_cmin is not None and act_cmin != exp_cmin:
                by_check["exposition_class"].append(_SpellIssue(
                    check="exposition_class", severity="error",
                    description=(
                        f"Cmin,dur mismatch for {governs}: "
                        f"drawing={act_cmin}, expected={exp_cmin} (Cnom Ø{ec_diameter})"
                    ),
                    page=1, location="title block BETONDECKUNG", confidence=1.0,
                ))
            if act_dc is not None and act_dc != exp_dc:
                by_check["exposition_class"].append(_SpellIssue(
                    check="exposition_class", severity="error",
                    description=(
                        f"ΔCdev mismatch for {governs}: "
                        f"drawing={act_dc}, expected={exp_dc}"
                    ),
                    page=1, location="title block BETONDECKUNG", confidence=1.0,
                ))
            if act_cv is not None and act_cv != exp_cv:
                by_check["exposition_class"].append(_SpellIssue(
                    check="exposition_class", severity="error",
                    description=(
                        f"Cv mismatch for {governs} at Ø{ec_diameter}: "
                        f"drawing={act_cv}, expected={exp_cmin}+{exp_dc}={exp_cv}"
                    ),
                    page=1, location="title block BETONDECKUNG", confidence=1.0,
                ))

    # ── steel_content Python computation ────────────────────────────────────
    sc_enabled = enabled_sub is None or "steel_content" in (enabled_sub or [])
    if sc_enabled:
        # Almost every sheet prints both numbers, so a missing one means the
        # coordinate rules did not fit this title block layout, not that the
        # value is absent. Read it off the rendered sheet before giving up.
        if not mass_str or not vol_str:
            print(
                f"[steel_content] gesamtmasse={mass_str!r} volumen={vol_str!r} — "
                f"falling back to a visual read of the rendered drawing"
            )
            vis_mass, vis_vol = _read_mass_volume_from_pdf(state.get("pdf_data"))
            if not mass_str and vis_mass:
                mass_str = vis_mass
                print(f"[steel_content] gesamtmasse taken from the visual read: {mass_str!r}")
            if not vol_str and vis_vol:
                vol_str = vis_vol
                print(f"[steel_content] volumen taken from the visual read: {vol_str!r}")

        sc_outcome = _evaluate_steel_content(mass_str, vol_str, sc_candidates)
        if sc_outcome.not_found:
            not_found_set.add("steel_content")
            if sc_outcome.not_found_desc:
                dynamic_not_found_descs["steel_content"] = sc_outcome.not_found_desc
        if sc_outcome.issue is not None:
            by_check["steel_content"].append(sc_outcome.issue)
        if sc_outcome.pass_desc:
            dynamic_pass_descs["steel_content"] = sc_outcome.pass_desc

    # ── lastausgleich Python check ────────────────────────────────────────────
    la_enabled = enabled_sub is None or "lastausgleich" in (enabled_sub or [])
    if la_enabled:
        if not la_ebt_found:
            not_found_set.add("lastausgleich")
            print("[lastausgleich] NOT FOUND — Einbauteilliste not in drawing")
        elif la_anchor_qty >= 4:
            if not la_text_present:
                by_check["lastausgleich"].append(_SpellIssue(
                    check="lastausgleich", severity="error",
                    description=(
                        f"Lifting anchors in the Einbauteilliste (max Menge={la_anchor_qty}) require "
                        f"a 'Lastausgleichgehänge' note in the drawing — not found"
                    ),
                    page=1, location="drawing / Einbauteilliste", confidence=1.0,
                ))
                print(f"[lastausgleich] FAIL — anchor qty={la_anchor_qty} >= 4 but Lastausgleichgehänge missing")
            else:
                print(f"[lastausgleich] PASS — anchor qty={la_anchor_qty} >= 4 and Lastausgleichgehänge present")
        else:  # < 4, including 0 = no lifting anchor in the Einbauteilliste
            if la_text_present:
                by_check["lastausgleich"].append(_SpellIssue(
                    check="lastausgleich", severity="error",
                    description=(
                        f"'Lastausgleichgehänge' note is present but the largest lifting-anchor "
                        f"Menge in the Einbauteilliste ({la_anchor_qty}) is below 4 — note not required"
                    ),
                    page=1, location="drawing", confidence=1.0,
                ))
                print(f"[lastausgleich] FAIL — qty={la_anchor_qty} < 4 but Lastausgleichgehänge present")
            else:
                print(f"[lastausgleich] PASS — qty={la_anchor_qty} < 4 and Lastausgleichgehänge absent")

    # ── overview_plan_check: compare title block with overview plan table ──────
    op_enabled = enabled_sub is None or "overview_plan_check" in (enabled_sub or [])
    # Preferred route: the element code printed in the sheet's top-left corner
    # ("ST-11-01") also names the element on the overview plan, both in its table
    # row and in the callout block drawn beside it. Looking the element up by
    # that code gets the plan's own figures for this exact element, which the
    # Drawing-No. route cannot do on plans whose table carries no volume or
    # weight column at all.
    op_code = str(title_block.get("element_code_top_left") or "").strip().upper()
    op_records: dict = (overview_plan_data or {}).get("element_records") or {}
    op_matched_record = op_records.get(op_code) if op_code else None
    if op_enabled and overview_plan_data:
        print(
            f"[overview_plan_check] top-left code={op_code!r}  "
            f"records on plan={len(op_records)}  matched={bool(op_matched_record)}"
        )

    if op_enabled and op_matched_record:
        print(f"[overview_plan_check] ── Element {op_code} ─────────────────────────────")
        print(f"[overview_plan_check]   plan states: {op_matched_record}")
        by_check["overview_plan_check"].extend(_compare_overview_element(
            op_code,
            op_matched_record,
            {
                "volumen":            op_vol_str,
                "gewicht":            op_wt_str,
                "anzahl":             op_qty_str,
                "statische_position": str(title_block.get("statische_position") or ""),
                "plan_id":            str(title_block.get("plan_id") or ""),
            },
        ))
        n = len(by_check["overview_plan_check"])
        print(f"[overview_plan_check] {'PASS' if n == 0 else f'FAIL — {n} mismatch(es)'}")
    elif op_enabled:
        if op_code and op_records:
            print(
                f"[overview_plan_check] {op_code!r} is not among the {len(op_records)} elements "
                f"the plan names — falling back to the Drawing-No. table match"
            )
        if not overview_plan_data or not overview_plan_data.get("element_rows"):
            not_found_set.add("overview_plan_check")
            print("[overview_plan_check] NOT FOUND — no overview plan, or neither the element code nor a table row matched")
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

            sl_stab  = str(sl_data.get("stabliste_total")       or "").strip()
            sl_matt  = str(sl_data.get("mattenstahlliste_total") or "").strip()

            # Read the Einbauteilliste tables in one combined call so the model
            # applies identical column logic to both. It reads the rendered PDF
            # documents (vision) when available — pdfplumber text drops narrow
            # cells like the Korrosionsschutz "FV" code — and falls back to text.
            dr_ebt, sl_ebt = _extract_ebt_tables(
                str(pdf_c.get("raw_text") or ""),
                str(sl_data.get("raw_text") or ""),
                drawing_pdf=state.get("pdf_data"),
                steel_list_pdf=sl_data.get("pdf_data"),
            )

            # Row-by-row schedules. Matching totals prove nothing on their own —
            # a position can be renumbered, or carry a different count or length,
            # while both documents still sum to the same mass.
            dr_bar, sl_bar, dr_mesh, sl_mesh = _extract_steel_schedules(
                str(pdf_c.get("raw_text") or ""),
                str(sl_data.get("raw_text") or ""),
                drawing_pdf=state.get("pdf_data"),
                steel_list_pdf=sl_data.get("pdf_data"),
            )

            print(f"[steel_list_check] ── Comparison ──────────────────────────────────")
            print(f"[steel_list_check]   Stabliste Gesamtmasse   : drawing={dr_stab!r}  steel_list={sl_stab!r}")
            print(f"[steel_list_check]   Mattenstahl Gesamtgewicht: drawing={dr_matt!r}  steel_list={sl_matt!r}")
            print(f"[steel_list_check]   Stabliste rows          : drawing={len(dr_bar)}  steel_list={len(sl_bar)}")
            print(f"[steel_list_check]   Mattenstahlliste rows   : drawing={len(dr_mesh)}  steel_list={len(sl_mesh)}")
            print(f"[steel_list_check]   EBT items               : drawing={len(dr_ebt)}  steel_list={len(sl_ebt)}")
            print(f"[steel_list_check] ────────────────────────────────────────────────")

            _SL_TOL = 0.01  # 1% relative tolerance

            def _sl_cmp_float(label: str, dr_val: str, sl_val: str, unit: str = "kg") -> None:
                # Nothing to compare against is not a defect: a sheet with no
                # Mattenstahlliste has no total on either document, and the old
                # order reported that as "could not extract (steel list has kg)".
                if not sl_val:
                    print(f"[steel_list_check]   SKIP {label}: the steel list states no value")
                    return
                if not dr_val:
                    print(f"[steel_list_check]   ERROR {label}: could not extract from drawing PDF")
                    by_check["steel_list_check"].append(_SpellIssue(
                        check="steel_list_check", severity="error",
                        description=f"{label}: could not extract value from drawing PDF (steel list has {sl_val} {unit})",
                        page=1, location=f"drawing {label}", confidence=1.0,
                    ))
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

            # Per-position comparison of both schedules — identical rules for the
            # bar list and the mesh list, and no tolerance: every column of a
            # position must agree exactly. Only the totals above carry one.
            by_check["steel_list_check"].extend(
                _compare_schedule("Stabliste", dr_bar, sl_bar)
            )
            by_check["steel_list_check"].extend(
                _compare_schedule("Mattenstahlliste", dr_mesh, sl_mesh)
            )

            # NOT FOUND only when nothing at all could be compared. A schedule the
            # drawing does not carry is not a defect, and it must not suppress the
            # findings of the comparisons that did run.
            compared_anything = bool(
                dr_ebt or sl_ebt or dr_bar or sl_bar or dr_mesh or sl_mesh
                or (dr_stab and sl_stab) or (dr_matt and sl_matt)
            )
            if not compared_anything:
                not_found_set.add("steel_list_check")
                print("[steel_list_check] NOT FOUND — no schedule or parts table in drawing or steel list")

            # EBT comparison — all 5 fields must match exactly
            dr_ebt_map = {_normalize_ebt_nr(item["ebt_nr"]): item for item in dr_ebt}
            sl_ebt_map = {_normalize_ebt_nr(item["ebt_nr"]): item for item in sl_ebt}

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
                        if not _ebt_field_matches(field_key, dr_val, sl_val, dr_item, sl_item):
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

    issues = build_check_issues(
        "spell",
        _CHECK_META,
        by_check,
        not_found_set,
        enabled_sub,
        dynamic_pass_descs,
        dynamic_not_found_descs,
    )
    issues.extend(run_user_ai_checks("spell", state))

    return {"spell_issues": issues}
