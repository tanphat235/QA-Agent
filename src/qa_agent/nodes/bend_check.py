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

_TASK_INTRO = """\
Review the bar schedule (Stabliste), mesh schedule (Mattenstahlliste), and rebar schemas in this structural drawing.
Report ONLY issues you can directly observe from clearly visible values in the PDF.\
"""

_CHECK_PROMPTS: dict[str, str] = {
    "pos_count": """\
CHECK — Last Position Number vs Title Block (pos_count)
The title block contains two fields that declare the last (highest) position number used:
  • "letzte Stabstahlposition" — last regular bar position in the Stabliste
  • "letzte Mattenposition"    — last mesh position in the Mattenstahlliste (if mesh is present)

PROCEDURE for Stabliste:
  1. Scan the Stabliste and find the highest Pos number that is ≤ 99 (ignore Pos 100+ completely).
  2. Read the value in the "letzte Stabstahlposition" field of the title block.
  3. If highest_pos_≤99 == title_block_value → PASS, do NOT flag anything.
  4. If highest_pos_≤99 ≠ title_block_value → flag as an issue.

PROCEDURE for Mattenstahlliste (only if the table is present on the sheet):
  1. Find the highest Pos number listed in the Mattenstahlliste.
  2. Read the value in the "letzte Mattenposition" field of the title block.
  3. If highest_mesh_pos == title_block_value → PASS, do NOT flag anything.
  4. If highest_mesh_pos ≠ title_block_value → flag as an issue.

IMPORTANT:
  • The presence of Pos 100, 101, 102, … in the Stabliste is normal and expected.
    These are special accessory bars. They do NOT affect letzte Stabstahlposition at all.
    If the title block value equals the highest regular Pos (≤99), the check PASSES — period.
  • Only flag when the numbers clearly and unambiguously differ.

If "letzte Stabstahlposition" is not visible in the title block, add "pos_count" to not_found.
If Mattenstahlliste is absent, skip the mesh part of this check (do NOT add to not_found for that).\
""",

    "pos_coverage": """\
CHECK — Pos Coverage in Schemas (pos_coverage)
Cross-reference every Pos number in the Stabliste with ALL representations visible anywhere on the sheet.

WHAT COUNTS AS COVERAGE FOR A POS — any of the following satisfies the requirement:
  A. A bar-shape sketch (bent or straight) shown in the margin or alongside a section view
     (Schnitt a-a, Schnitt b-b, Schnitt c-c, Bewehrung, etc.) with the Pos number adjacent.
     The sketch can be as simple as an L-shape, U-shape, or straight line segment.
  B. A bar annotation in any section or plan view that shows:
       Pos number  +  quantity × diameter  (e.g. "2 ø 12" or "4 × Ø8")
     Even without a separate drawn shape — if the Pos is labeled in a section with its bar
     dimensions, that counts as coverage.
  C. An annotation of the form  "n ø d / spacing"  or  "n ø d -M.E."  next to a position
     in any Schnitt or Bewehrung view — distributed and spacer bars are covered this way.
  D. A combined label like  "n × Ø d  L=xxx cm"  shown anywhere on the sheet adjacent to
     a bar representation, whether or not a formal schema box is drawn.
  E. A shared schema or note explicitly listing multiple Pos numbers covers ALL of them.

WHERE TO LOOK — search ALL of the following areas:
  • Left and right margin columns of every Schnitt section (a-a, b-b, c-c, etc.)
  • Top and bottom margin areas of every Schnitt section
  • The Bewehrung plan/elevation area — inline sketches with leader lines
  • Any Detail panels or callout boxes on the sheet
  • Dimension annotation areas around section cross-sections

PROCEDURE:
  1. List every Pos number from the Stabliste.
  2. Scan ALL areas listed above for any coverage representation (A–E) for each Pos.
  3. Only flag a Pos if you found absolutely NO coverage after searching the full sheet.

FLAG only if confidence ≥ 0.80 that coverage is genuinely absent from the ENTIRE sheet.
Do NOT flag if coverage might exist but is small, partially hidden, or hard to read.\
""",

    "mesh_pos": """\
CHECK — Mesh Reinforcement Pos (mesh_pos)
This check requires BOTH of the following tables to be present on the sheet:
  • Mattenstahlliste (mesh rebar schedule)
  • Matten-Schneideskizze (mesh cut sketch)
If both are present, verify each mesh Pos listed in the Mattenstahlliste appears in at least one view of the Matten-Schneideskizze.
Flag any mesh Pos that is listed in the Mattenstahlliste but has no corresponding entry in the Matten-Schneideskizze.
If either Mattenstahlliste or Matten-Schneideskizze is absent from the sheet, add "mesh_pos" to not_found.\
""",

    "mesh_ratio": """\
CHECK — Mesh-to-Total Mass Ratio (mesh_ratio)
This check requires BOTH Stabliste and Mattenstahlliste to be present on the sheet.
If both are present, calculate:
  ratio = (total_mesh_mass / (total_rebar_mass + total_mesh_mass)) × 100
Flag if ratio < 85 %.
Obtain totals from the "Gesamt" (total) rows of each schedule.
If either Stabliste or Mattenstahlliste is absent, or if the Gesamt totals are not clearly visible, add "mesh_ratio" to not_found.\
""",

    "mass_arithmetic": """\
CHECK — Total Mass Arithmetic (mass_arithmetic)
Verify that the Gesamtmasse (grand total mass) at the bottom of the Stabliste equals the sum
of all individual row Masse [kg] values.

PROCEDURE:
  1. Read every row's Masse [kg] value from the Stabliste.
  2. Sum them: computed_total = Σ Masse_i
  3. Read the Gesamtmasse [kg] footer value.
  4. If computed_total ≠ Gesamtmasse → flag immediately. Any difference is an error.

If the Mattenstahlliste is also present, apply the same check to it independently.

Do NOT flag if individual row values or the Gesamtmasse footer are not clearly readable.
If the Gesamtmasse footer is absent or illegible, add "mass_arithmetic" to not_found.\
""",

    "bending_angle": """\
CHECK — Bending Angle / Mandrel Diameter (bending_angle)
For each rebar schema, verify any explicitly labeled mandrel diameter using these minimum values:
  Ø8  → factor 4, min. dbr = 3.2 cm
  Ø10 → factor 4, min. dbr = 4.0 cm
  Ø12 → factor 4, min. dbr = 4.8 cm
  Ø16 → factor 4, min. dbr = 6.4 cm
  Ø20 → factor 7, min. dbr = 14.0 cm
  Ø24 → factor 7, min. dbr = 16.8 cm
  Ø28 → factor 7, min. dbr = 19.6 cm
Flag if a labeled mandrel diameter in the schema is clearly below the minimum for that bar size.
Do NOT flag unlabeled bending radii or diameters.\
""",

    "bar_length": """\
CHECK — Bar Length vs Schedule (bar_length)
For each rebar schema where a total length L is explicitly shown, compare it with the "Einzel Länge" in the Stabliste.
Flag if the schema length clearly differs from the schedule value.
If the schema total length or Einzel Länge values are not explicitly shown, add "bar_length" to not_found.\
""",
}

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
  • Only report what is directly visible and unambiguous in the drawing.
  • Do NOT infer or estimate values not shown.
  • If required information is absent from the drawing, add the check key to not_found instead of skipping.
  • If no issues are found for all checks, return an empty issues list and an empty not_found list — that is correct.\
"""


def _build_bend_task(enabled_sub: list[str] | None) -> str:
    active = list(_CHECK_PROMPTS.keys()) if enabled_sub is None else [k for k in enabled_sub if k in _CHECK_PROMPTS]
    check_keys = " | ".join(f'"{k}"' for k in active)
    blocks = "\n\n".join(_CHECK_PROMPTS[k] for k in active)
    return _TASK_INTRO + "\n\n" + blocks + _TASK_OUTRO_TPL.format(check_keys=check_keys)

# Python generates pass/fail summaries — LLM never needs to produce them.
# Tuple: (display_name, pass_desc, not_found_desc)
_CHECK_META: dict[str, tuple[str, str, str]] = {
    "pos_count": (
        "Last Position Number vs Title Block",
        "PASS — letzte Stabstahlposition and letzte Mattenposition match schedule tables.",
        "NOT FOUND — 'letzte Stabstahlposition' field not visible in title block.",
    ),
    "pos_coverage": (
        "Pos Coverage",
        "PASS — all Stabliste positions have a corresponding schema.",
        "NOT FOUND — Stabliste not found on sheet.",
    ),
    "mesh_pos": (
        "Mesh Reinforcement Pos",
        "PASS — all mesh positions appear in section views.",
        "NOT FOUND — Mattenstahlliste or Matten-Schneideskizze absent from sheet.",
    ),
    "mesh_ratio": (
        "Mesh-to-Total Mass Ratio",
        "PASS — mesh reinforcement ratio ≥ 85 %.",
        "NOT FOUND — Mattenstahlliste absent or Gesamtmasse totals not visible.",
    ),
    "mass_arithmetic": (
        "Total Mass Arithmetic",
        "PASS — sum of row masses matches Gesamtmasse footer.",
        "NOT FOUND — Gesamtmasse footer absent or illegible.",
    ),
    "bending_angle": (
        "Bending Angle / Mandrel Diameter",
        "PASS — all labeled mandrel diameters comply with minimum requirements.",
        "NOT FOUND — no labeled mandrel diameters found in schemas.",
    ),
    "bar_length": (
        "Bar Length vs Schedule",
        "PASS — all schema lengths match Einzel Länge in Stabliste.",
        "NOT FOUND — schema total lengths or Einzel Länge values not visible.",
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


class _BendIssue(BaseModel):
    check: str = Field(description="pos_count | pos_coverage | mesh_pos | mesh_ratio | mass_arithmetic | bending_angle | bar_length")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _BendResult(BaseModel):
    issues: list[_BendIssue]  # required — no default so missing field raises ValidationError
    not_found: list[str] = Field(default_factory=list, description="Check keys where required drawing information was not visible")


# pos_coverage requires a higher confidence bar to suppress false positives.
_HIGH_CONFIDENCE_CHECKS = {"pos_coverage"}


def _group_bend_issue(item: _BendIssue, by_check: dict[str, list[_BendIssue]]) -> None:
    if item.check not in by_check:
        return
    threshold = 0.80 if item.check in _HIGH_CONFIDENCE_CHECKS else 0.60
    if item.confidence >= threshold:
        by_check[item.check].append(item)


def _build_bend_summary(check_key: str, check_name: str, pass_desc: str, nf_desc: str,
                        found: list[_BendIssue], not_found_set: set[str]) -> list[Issue]:
    """Return the summary item (and individual findings) for one bend check."""
    if check_key in not_found_set:
        return [Issue(  # type: ignore[call-arg]
            category="bend", check_name=check_name, not_found=True,
            severity="info",
            description=nf_desc,
            page=1, location="drawing", confidence=1.0,
        )]
    passed = len(found) == 0
    if passed:
        summary_desc = pass_desc
    elif len(found) == 1:
        summary_desc = f"FAIL — {found[0].description}"
    else:
        summary_desc = f"FAIL — {len(found)} issue(s) found."
    items: list[Issue] = [Issue(  # type: ignore[call-arg]
        category="bend", check_name=check_name, passed=passed,
        severity="info" if passed else "error",
        description=summary_desc, page=1, location="drawing", confidence=1.0,
    )]
    for item in found:
        items.append(Issue(  # type: ignore[call-arg]
            category="bend", severity=item.severity,
            description=item.description, page=item.page,
            location=item.location, confidence=item.confidence,
        ))
    return items


def bend_check(state: GraphState) -> dict:
    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]
    enabled_sub = (state.get("enabled_sub_checks") or {}).get("bend")

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_BendResult).with_retry(stop_after_attempt=2)

    kb_images = get_node_images("bend")
    human_content: list[dict] = []
    # Knowledge reference images first (static → cache-friendly)
    for i, img in enumerate(kb_images):
        block = dict(img)
        if i == len(kb_images) - 1:
            block["cache_control"] = {"type": "ephemeral"}
        human_content.append(block)
    # Drawing PDF
    human_content.append({
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
        "cache_control": {"type": "ephemeral"},
    })
    human_content.append({"type": "text", "text": _build_bend_task(enabled_sub) + get_node_context("bend")})

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
        _group_bend_issue(item, by_check)

    not_found_set = set(result.not_found or [])

    issues: list[Issue] = []
    for check_key, (check_name, pass_desc, nf_desc) in _CHECK_META.items():
        if enabled_sub is not None and check_key not in enabled_sub:
            continue
        issues.extend(_build_bend_summary(check_key, check_name, pass_desc, nf_desc, by_check[check_key], not_found_set))

    return {"bend_issues": issues}
