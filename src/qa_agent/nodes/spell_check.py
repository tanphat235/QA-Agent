import logging
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.outputs import LLMResult

from qa_agent.state import GraphState, Issue
from qa_agent.rag.retriever import get_node_context, get_node_images

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

_TASK = """\
Inspect visible text, annotations, views, and tables in this precast wall structural drawing.
Report ONLY issues you can directly observe in the PDF.

CHECK 1 — Spelling Errors (spelling)
Flag clear spelling mistakes in German or English words in titles, labels, notes, callouts, or title block.
Do NOT flag: accepted engineering abbreviations (Ø, typ., M.E., Reinf., Bew., pos.), capitalization style.

CHECK 2 — Section Name Completeness (section_name)
Identify all section cut designations called out in the Ansicht or Bewehrung (e.g. "1-1", "2-2", "3-3").
Verify that a corresponding view with the same designation number is present on the sheet.
A view satisfies the requirement if it is labeled "Schnitt X-X", "Draufsicht X-X", or any other
view type (top view, cross-section, detail) that carries the same designation number X-X.
Flag only if NO view of any type with that designation number exists anywhere on the sheet.
Do NOT flag if the view exists but is located elsewhere on the sheet.

CHECK 3 — Component Name vs Title Block (component_name)
Verify the component/element name on the Wandansicht matches the drawing name in the title block.
Flag only where BOTH are visible and they clearly differ.
If only one of the two (Wandansicht label or title block name) is visible, add "component_name" to not_found.

CHECK 4 — Scale Consistency (section_scale)
Compare every explicit scale label (M 1:XX) on views or sections against the title block scale.
Flag any view whose labeled scale clearly differs from the title block value.
Only flag where both scales are simultaneously visible and unambiguously different.

CHECK 5 — Formwork Grid Lines vs Wandansicht (grid_lines)
Check that grid lines (axis labels / column lines) in the wall formwork Schnitt views match those in the Wandansicht.
Flag any grid line present in the Schnitt but absent from the Wandansicht, or vice versa.
If no Wandansicht is visible on the sheet, add "grid_lines" to not_found.

CHECK 6 — Parts Lists Present (parts_lists)
Verify the sheet contains both:
  • Einbauteilliste (embedded parts list)
  • Montageteilliste (assembly/mounting parts list)
Flag each table that is clearly absent.

CHECK 7 — Parts Label Consistency (parts_quantities)
PREREQUISITE: Both Einbauteilliste AND Montageteilliste must be present on the sheet.
If either or both tables are absent (flagged in CHECK 6), add "parts_quantities" to not_found
and skip this check entirely — do NOT attempt to cross-reference.

If both tables are present: cross-reference every part label visible in Schnitt and Ansicht views.
  1. UNLABELED PARTS — any built-in or mounting part with NO label. Flag each.
  2. LABEL NOT IN TABLE — any label code in views NOT in Einbauteilliste or Montageteilliste. Flag each.
RULES:
  • A label found in EITHER table is consistent — do NOT flag it.
  • Do NOT flag rebar Pos numbers — only flag embedded/mounting part designations.
  • Only flag when you can clearly read the label AND confirm it is absent from both tables.

CHECK 8 — Built-in Part Labels (parts_labels)
PREREQUISITE: At least one of Einbauteilliste or Montageteilliste must be present on the sheet.
If BOTH tables are absent (flagged in CHECK 6), add "parts_labels" to not_found and skip.

If at least one table is present: count all built-in parts visible in section and elevation views.
Verify each part has an explicit label (position number or designation) shown directly adjacent
or via leader line. Flag any built-in part shown without a label.

CHECK 9 — 3D View Present (3d_view)
Check whether the sheet contains a 3D pictorial view of the wall element.

WHAT COUNTS AS A 3D VIEW — ANY ONE of the following is sufficient to pass:

  LABELED VIEWS (pass regardless of visual appearance):
  • Any area or view titled "3D Perspektive", "Perspektive", "isometrische Ansicht",
    "3D Ansicht", "3D View", or any text containing "3D" or "Perspektiv".

  UNLABELED VIEWS (visual recognition — no label required):
  • A drawing of the wall body shown from a diagonal/oblique angle (approximately 45°),
    where the wall appears as a solid rectangular block or slab tilted toward the viewer.
  • Telltale signs: the main face of the wall AND at least one side edge or top edge are
    visible simultaneously; the wall outline lines run diagonally (not purely horizontal
    or vertical); the view gives an overall "bird's eye" or "overview" impression of the
    entire wall element in three dimensions.
  • This type of view is a standard engineering axonometric or isometric line drawing.
    It is typically placed in a corner of the sheet, often without any scale label or title.
    It may show embedded hardware, rebar protruding from the wall face, lifting anchors, etc.
  • Shading, color, or fill are NOT required — a pure line drawing counts.
  • The view may be small or appear in a corner of the sheet — size does not matter.

HOW TO SCAN:
  Look at ALL areas of the sheet, including corners and margins. If you see a rectangular
  wall-shaped outline drawn at a diagonal angle (showing depth), that IS the 3D view.

If ANY such view exists anywhere on the sheet → PASS immediately, do NOT flag.
If after scanning the entire sheet no such view exists → flag as an error.

Do NOT perform any consistency or orientation check — presence alone is sufficient.

CHECK 10 — Drawing Title vs Title Block (drawing_title)
Locate the drawing title shown prominently at the top of the sheet (the main heading above the
drawing views, often in a large font or header area).
Also find the Drawing Title field inside the title block (Schriftfeld / title block area, usually
in the lower-right corner of the sheet).

MATCHING RULE:
  The title block Drawing Title field may contain a bilingual entry with German and English
  separated by "/" (e.g. "Schalung und Bewehrung ... / Formwork and reinforcement ...").
  In that case, compare ONLY the German part (the text before the "/" separator) against the
  sheet heading. Minor punctuation differences (trailing period, dash spacing) are acceptable.
  Flag only if the semantic content clearly differs — e.g. different element name, wrong axis label.

  If the title block field contains only one language, compare it directly to the sheet heading.

If the sheet heading is not visible, or the title block Drawing Title field is not visible,
add "drawing_title" to not_found.
Do NOT flag if both texts convey the same meaning with only formatting/punctuation differences.

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       "spelling" | "section_name" | "component_name" | "section_scale" | "grid_lines" | "parts_lists" | "parts_quantities" | "parts_labels" | "3d_view" | "drawing_title"
  severity:    "error" for clear non-compliance; "warning" for ambiguous or minor
  description: concise — quote the specific text, field, label, or count involved
  page:        1
  location:    specific location (e.g. "Wandansicht element label" or "title block drawing name field")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65
  not_found:   list of check keys where prerequisite drawing elements were absent, e.g. ["grid_lines"]

RULES:
  • Only report issues directly visible and unambiguous.
  • Do NOT flag uncertain or marginally readable text.
  • If prerequisite drawing elements are absent, add the check key to not_found instead of skipping.
  • If no issues are found for all checks, return an empty issues list and an empty not_found list — that is correct.\
"""

# Python generates pass/fail summaries — LLM never needs to produce them.
# Tuple: (display_name, pass_desc, not_found_desc)
_CHECK_META: dict[str, tuple[str, str, str]] = {
    "spelling": (
        "Spelling Check",
        "PASS — no spelling errors found in drawing text.",
        "NOT FOUND — no readable text found on sheet.",
    ),
    "section_name": (
        "Section Name Completeness",
        "PASS — all section cuts in Ansicht/Bewehrung have a corresponding Schnitt view.",
        "NOT FOUND — no section cut designations found in Ansicht or Bewehrung.",
    ),
    "component_name": (
        "Component Name vs Title Block",
        "PASS — Wandansicht component name matches title block.",
        "NOT FOUND — Wandansicht element label or title block name not visible.",
    ),
    "section_scale": (
        "Scale Consistency",
        "PASS — all view scales consistent with title block.",
        "NOT FOUND — no scale labels (M 1:XX) visible on views or title block.",
    ),
    "grid_lines": (
        "Formwork Grid Lines Consistency",
        "PASS — grid lines in Schnitt views match Wandansicht.",
        "NOT FOUND — Wandansicht absent from sheet.",
    ),
    "parts_lists": (
        "Parts Lists Present",
        "PASS — Einbauteilliste and Montageteilliste both present.",
        "NOT FOUND — neither Einbauteilliste nor Montageteilliste visible on sheet.",
    ),
    "parts_quantities": (
        "Parts Quantities Consistent",
        "PASS — built-in and mounting part counts match schedules.",
        "NOT FOUND — no part labels or schedule tables visible.",
    ),
    "parts_labels": (
        "Built-in Part Labels",
        "PASS — all built-in parts are labeled in section/elevation views.",
        "NOT FOUND — no built-in parts visible in section or elevation views.",
    ),
    "3d_view": (
        "3D View Present and Consistent",
        "PASS — 3D view present and consistent with Ansicht.",
        "NOT FOUND — no 3D pictorial (oblique/isometric) view found on sheet.",
    ),
    "drawing_title": (
        "Drawing Title vs Title Block",
        "PASS — sheet heading matches title block Drawing Title field.",
        "NOT FOUND — sheet heading or title block Drawing Title field not visible.",
    ),
}


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
    check: str = Field(description="spelling | section_name | component_name | section_scale | grid_lines | parts_lists | parts_quantities | parts_labels | 3d_view | drawing_title")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _SpellResult(BaseModel):
    issues: list[_SpellIssue]  # required — no default so missing field raises ValidationError
    not_found: list[str] = Field(default_factory=list, description="Check keys where prerequisite drawing elements were absent")


def _build_spell_summary(check_key: str, check_name: str, pass_desc: str, nf_desc: str,
                         found: list[_SpellIssue], not_found_set: set[str]) -> list[Issue]:
    """Return the summary item (and individual findings) for one spell check."""
    if check_key in not_found_set:
        return [{
            "category": "spell",
            "check_name": check_name,
            "not_found": True,
            "severity": "info",
            "description": nf_desc,
            "page": 1,
            "location": "drawing",
            "confidence": 1.0,
        }]
    passed = len(found) == 0
    if passed:
        summary_desc = pass_desc
    elif len(found) == 1:
        summary_desc = f"FAIL — {found[0].description}"
    else:
        summary_desc = f"FAIL — {len(found)} issue(s) found."
    items: list[Issue] = [{
        "category": "spell",
        "check_name": check_name,
        "passed": passed,
        "severity": "info" if passed else "error",
        "description": summary_desc,
        "page": 1,
        "location": "drawing",
        "confidence": 1.0,
    }]
    for item in found:
        items.append({
            "category": "spell",
            "severity": item.severity,
            "description": item.description,
            "page": item.page,
            "location": item.location,
            "confidence": item.confidence,
        })
    return items


def spell_check(state: GraphState) -> dict:
    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
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
    human_content.append({"type": "text", "text": _TASK + get_node_context("spell")})

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
        if item.confidence >= 0.60 and item.check in by_check:
            by_check[item.check].append(item)

    not_found_set = set(result.not_found or [])

    # If parts tables are absent, dependent checks cannot run
    if by_check.get("parts_lists"):
        not_found_set.add("parts_quantities")
        not_found_set.add("parts_labels")

    issues: list[Issue] = []
    for check_key, (check_name, pass_desc, nf_desc) in _CHECK_META.items():
        issues.extend(_build_spell_summary(check_key, check_name, pass_desc, nf_desc, by_check[check_key], not_found_set))

    return {"spell_issues": issues}
