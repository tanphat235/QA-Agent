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
Inspect reinforcement elements, spacers, pin bars, and clamps in this precast wall structural drawing.
Report ONLY issues you can directly observe from visible annotations and dimensions in the PDF.

CHECK 1 — Spacer / Clamp Label Suffix (spacer_label)
Use the "-M.E." suffix itself to identify which Pos numbers are spacers/clamps, then verify every
label for those positions also carries the suffix.

PROCEDURE — two steps:

  STEP 1 — Identify spacer/clamp positions:
    Scan the entire drawing for any label that ends with "-M.E." (e.g. "11-M.E.", "Ø8-M.E.", "Pos 17-M.E.").
    Extract the Pos number from each such label.  These are the spacer/clamp positions.
    Example: if you see "11-M.E." and "17-M.E.", then Pos 11 and Pos 17 are spacer/clamp positions.

  STEP 2 — Check ALL labels for each identified spacer/clamp Pos:
    For every Pos identified in Step 1, find every place in the drawing where that Pos is labeled
    (Stabliste rows, bending schemas, section callouts, Bewehrung annotations, dimension leaders, etc.).
    Flag any label of that Pos that does NOT end with "-M.E.".

EXAMPLE:
  Pos 11 is found labeled "11-M.E." in the schema → Pos 11 is a spacer.
  If "11" appears in the Stabliste or a section without the "-M.E." suffix → FAIL.
  If all occurrences of Pos 11 include "-M.E." → PASS for Pos 11.

Do NOT flag Pos numbers that never appear with "-M.E." anywhere — those are not spacers/clamps.
Do NOT flag if you cannot clearly read the label.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO FIND THE SHARED DIMENSIONS (used in CHECK 2, 3, 4)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

wall_width — total wall thickness in cm:
  Look at the FORMWORK cross-section views (Draufsicht X-X, Schnitt X-X in the Ansicht/
  formwork area, NOT the Bewehrung area). A small dimension line spanning the full wall
  thickness will show the value (e.g. "30" = 30 cm). It may also appear in the title block.

Cv — design concrete cover in cm:
  Read from the title block "BETONDECKUNG" table. The column labeled "Cv" (or "Cᵥ") contains
  the design cover value in mm — divide by 10 to convert to cm.
  Example: Cv column shows "25" → Cv = 2.5 cm.
  Do NOT use Cmin,dur or ΔCdev — use only the Cv column value.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CHECK 2 — Vertical Pin Width (pin_width_vertical)
IDENTIFICATION — locate vertical pins using their bending schema:
  Vertical pins are schematized in the SIDE section view of the Bewehrung (e.g. Schnitt a-a).
  In that view, the pin schema appears as a narrow U-shape or rectangular stirrup whose long
  dimension runs vertically (tall and narrow). The width dimension labeled on that schema is
  the value to verify.

WIDTH FORMULA:
  Required width = wall_width – 2 × Cv
  Example: wall_width=30 cm, Cv=2.5 cm → required = 30 – 5.0 = 25 cm

HOW TO FIND wall_width and Cv: see the shared dimension guide above.
Flag if the labeled pin width clearly differs from the required calculated value.
If wall_width, Cv, or the labeled pin dimension cannot be found, add "pin_width_vertical" to not_found.

CHECK 3 — Horizontal Pin Width (pin_width_horizontal)
IDENTIFICATION — locate horizontal pins using their bending schema:
  Horizontal pins are schematized in the BOTTOM / HORIZONTAL cross-section view of the Bewehrung
  (e.g. Schnitt b-b). In that view, the pin schema appears as a flat rectangular stirrup whose
  long dimension runs horizontally (wide and shallow). The width dimension labeled on that schema
  is the value to verify.

WIDTH FORMULA:
  Required width = wall_width – 2 × Cv – 2 × Ø_layer1   (round down to nearest mm)
  Example: wall_width=30, Cv=2.5, Ø_layer1=1.2 → 30 – 5.0 – 2.4 = 22.6 → 22 cm

HOW TO FIND Ø_layer1 (outermost rebar layer diameter):
  Look at the SIDE section view Schnitt a-a in the Bewehrung.
  Identify the first rebar layer counting from the wall face (outer edge) inward.
  Read the bar label for that layer — it will show diameter and spacing, e.g. "ø 12/15" means Ø12.
  Use that diameter: Ø_layer1 = 1.2 cm (for Ø12), 1.0 cm (for Ø10), 0.8 cm (for Ø8), etc.
  Do NOT use inner layers — only the outermost layer touching the cover zone.

HOW TO FIND wall_width and Cv: see the shared dimension guide above.
Flag if the labeled horizontal pin width clearly differs from the calculated value.
If any required dimension (wall_width, Cv, Ø_layer1, or pin width) cannot be found, add "pin_width_horizontal" to not_found.

CHECK 4 — Spacer / Clamp Width (spacer_width)
For each spacer or clamp element, verify its width using:
  Required width = wall_width – 2 × Cv + 2 × Ø_spacer   (round up to nearest mm)
  where Ø_spacer = physical diameter of the spacer/clamp wire or element (read from its label).
  Example: wall_width=30, Cv=2.5, Ø_spacer=0.8 → 30 – 5.0 + 1.6 = 26.6 → 27 cm

HOW TO FIND wall_width and Cv: see the shared dimension guide above.
Flag if the labeled spacer/clamp width clearly differs from the calculated value.
If any required dimension (wall_width, Cv, or Ø_spacer) cannot be found, add "spacer_width" to not_found.

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       "spacer_label" | "pin_width_vertical" | "pin_width_horizontal" | "spacer_width"
  severity:    "error" for missing/wrong label or incorrect dimension causing fabrication risk; "warning" for ambiguous
  description: concise — quote label text, or state: formula, calculated value, and declared value
  page:        1
  location:    specific location (e.g. "Schnitt 6-6, bottom spacer" or "wall side section, horizontal pin Pos 14")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65
  not_found:   list of check keys where required drawing information was not visible, e.g. ["pin_width_vertical"]

RULES:
  • Only report issues directly visible and unambiguous.
  • When flagging a dimension issue, state the formula and both values in the description.
  • If required dimensions or values are not visible in the drawing, add the check key to not_found instead of skipping.
  • If no issues are found for all checks, return an empty issues list and an empty not_found list — that is correct.\
"""

# Python generates pass/fail summaries — LLM never needs to produce them.
# Tuple: (display_name, pass_desc, not_found_desc)
_CHECK_META: dict[str, tuple[str, str, str]] = {
    "spacer_label": (
        "Spacer / Clamp Label Suffix",
        'PASS — all spacer and clamp labels include the "-M.E." suffix.',
        "NOT FOUND — no '-M.E.' labels found on sheet to identify spacer/clamp positions.",
    ),
    "pin_width_vertical": (
        "Vertical Pin Width",
        "PASS — all vertical pin widths match wall_width – 2×Cv.",
        "NOT FOUND — wall thickness, concrete cover (Cv), or labeled pin dimension not visible.",
    ),
    "pin_width_horizontal": (
        "Horizontal Pin Width",
        "PASS — all horizontal pin widths match wall_width – 2×Cv – 2×Ø_layer1.",
        "NOT FOUND — wall thickness, Cv, outer rebar diameter, or labeled pin dimension not visible.",
    ),
    "spacer_width": (
        "Spacer / Clamp Width",
        "PASS — all spacer/clamp widths match wall_width – 2×Cv + 2×Ø_spacer.",
        "NOT FOUND — wall thickness, Cv, or spacer wire diameter not visible.",
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


class _RebarIssue(BaseModel):
    check: str = Field(description="spacer_label | pin_width_vertical | pin_width_horizontal | spacer_width")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _RebarResult(BaseModel):
    issues: list[_RebarIssue]  # required — no default so missing field raises ValidationError
    not_found: list[str] = Field(default_factory=list, description="Check keys where required drawing dimensions were not visible")


def rebar_check(state: GraphState) -> dict:
    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,  # type: ignore[call-arg]
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_RebarResult).with_retry(stop_after_attempt=2)

    kb_images = get_node_images("rebar")
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
    human_content.append({"type": "text", "text": _TASK + get_node_context("rebar")})

    result: _RebarResult = llm.invoke(  # type: ignore[assignment]
        [
            SystemMessage(content=_COMMON_SYSTEM),
            HumanMessage(content=human_content),
        ],
        config={"callbacks": [_UsageCallback("rebar_check")]},
    )
    print(f"[usage][rebar_check] raw items from LLM: {len(result.issues)}")

    # Group LLM findings by check category, filter low-confidence
    by_check: dict[str, list[_RebarIssue]] = {k: [] for k in _CHECK_META}
    for item in result.issues:
        if item.confidence >= 0.60 and item.check in by_check:
            by_check[item.check].append(item)

    not_found_set = set(result.not_found or [])
    issues: list[Issue] = []

    # Python always generates a guaranteed pass/fail/not_found summary for every check
    for check_key, (check_name, pass_desc, nf_desc) in _CHECK_META.items():
        if check_key in not_found_set:
            issues.append({
                "category": "rebar",
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
        if passed:
            summary_desc = pass_desc
        elif len(found) == 1:
            summary_desc = f"FAIL — {found[0].description}"
        else:
            summary_desc = f"FAIL — {len(found)} issue(s) found."
        issues.append({
            "category": "rebar",
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
                "category": "rebar",
                "severity": item.severity,
                "description": item.description,
                "page": item.page,
                "location": item.location,
                "confidence": item.confidence,
            })

    return {"rebar_issues": issues}
