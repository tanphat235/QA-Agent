import logging
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.outputs import LLMResult

from qa_agent.state import GraphState, Issue

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
Verify that a corresponding "Schnitt X-X" view is present on the sheet for every designated cut.
Flag any cut designation whose Schnitt view is absent from the sheet.
Do NOT flag if the Schnitt view exists but is located elsewhere on the sheet.

CHECK 3 — Component Name vs Title Block (component_name)
Verify the component/element name on the Wandansicht matches the drawing name in the title block.
Flag only where BOTH are visible and they clearly differ.
Do NOT flag if only one is visible.

CHECK 4 — Scale Consistency (section_scale)
Compare every explicit scale label (M 1:XX) on views or sections against the title block scale.
Flag any view whose labeled scale clearly differs from the title block value.
Only flag where both scales are simultaneously visible and unambiguously different.

CHECK 5 — Formwork Grid Lines vs Wandansicht (grid_lines)
Check that grid lines (axis labels / column lines) in the wall formwork Schnitt views match those in the Wandansicht.
Flag any grid line present in the Schnitt but absent from the Wandansicht, or vice versa.
Do NOT flag if no Wandansicht is visible on the sheet.

CHECK 6 — Parts Lists Present (parts_lists)
Verify the sheet contains both:
  • Einbauteilliste (embedded parts list)
  • Montageteilliste (assembly/mounting parts list)
Flag each table that is clearly absent.

CHECK 7 — Parts Quantities Consistent (parts_quantities)
For each built-in part and mounting part shown in the Schnitt and Ansicht:
Compare the count visible in the drawing views against the quantity in the Einbauteilliste / Montageteilliste.
Flag any part whose visible count clearly differs from its scheduled quantity.
Do NOT flag if the part cannot be identified in both the view and the schedule simultaneously.

CHECK 8 — Built-in Part Labels (parts_labels)
Count all built-in parts visible in the section and elevation views.
Verify each part has an explicit label (position number or designation) shown directly adjacent or via leader line.
Flag any built-in part shown without a label.

CHECK 9 — 3D View Present and Consistent (3d_view)
Verify the sheet includes a 3D view (isometric or perspective) of the wall element.
If present, check the 3D view is consistent with the Ansicht (same openings, cutouts, and part positions).
Flag if: the 3D view is absent, or if it clearly contradicts the Ansicht.

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       "spelling" | "section_name" | "component_name" | "section_scale" | "grid_lines" | "parts_lists" | "parts_quantities" | "parts_labels" | "3d_view"
  severity:    "error" for clear non-compliance; "warning" for ambiguous or minor
  description: concise — quote the specific text, field, label, or count involved
  page:        1
  location:    specific location (e.g. "Wandansicht element label" or "title block drawing name field")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65

RULES:
  • Only report issues directly visible and unambiguous.
  • Do NOT flag uncertain or marginally readable text.
  • If no issues are found for all checks, return an empty list — that is correct.\
"""

# Python generates pass/fail summaries — LLM never needs to produce them.
_CHECK_META: dict[str, tuple[str, str]] = {
    "spelling": (
        "Spelling Check",
        "PASS — no spelling errors found in drawing text.",
    ),
    "section_name": (
        "Section Name Completeness",
        "PASS — all section cuts in Ansicht/Bewehrung have a corresponding Schnitt view.",
    ),
    "component_name": (
        "Component Name vs Title Block",
        "PASS — Wandansicht component name matches title block.",
    ),
    "section_scale": (
        "Scale Consistency",
        "PASS — all view scales consistent with title block.",
    ),
    "grid_lines": (
        "Formwork Grid Lines Consistency",
        "PASS — grid lines in Schnitt views match Wandansicht.",
    ),
    "parts_lists": (
        "Parts Lists Present",
        "PASS — Einbauteilliste and Montageteilliste both present.",
    ),
    "parts_quantities": (
        "Parts Quantities Consistent",
        "PASS — built-in and mounting part counts match schedules.",
    ),
    "parts_labels": (
        "Built-in Part Labels",
        "PASS — all built-in parts are labeled in section/elevation views.",
    ),
    "3d_view": (
        "3D View Present and Consistent",
        "PASS — 3D view present and consistent with Ansicht.",
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
    check: str = Field(description="spelling | section_name | component_name | section_scale | grid_lines | parts_lists | parts_quantities | parts_labels | 3d_view")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _SpellResult(BaseModel):
    issues: list[_SpellIssue]  # required — no default so missing field raises ValidationError


def spell_check(state: GraphState) -> dict:
    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_SpellResult).with_retry(stop_after_attempt=2)

    result: _SpellResult = llm.invoke(  # type: ignore[assignment]
        [
            SystemMessage(content=_COMMON_SYSTEM),
            HumanMessage(content=[
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": _TASK,
                },
            ]),
        ],
        config={"callbacks": [_UsageCallback("spell_check")]},
    )
    print(f"[usage][spell_check] raw items from LLM: {len(result.issues)}")

    # Group LLM findings by check category, filter low-confidence
    by_check: dict[str, list[_SpellIssue]] = {k: [] for k in _CHECK_META}
    for item in result.issues:
        if item.confidence >= 0.60 and item.check in by_check:
            by_check[item.check].append(item)

    issues: list[Issue] = []

    # Python always generates a guaranteed pass/fail summary for every check
    for check_key, (check_name, pass_desc) in _CHECK_META.items():
        found = by_check[check_key]
        passed = len(found) == 0
        if passed:
            summary_desc = pass_desc
        elif len(found) == 1:
            summary_desc = f"FAIL — {found[0].description}"
        else:
            summary_desc = f"FAIL — {len(found)} issue(s) found."
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
