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
Review the bar schedule (Stabliste), mesh schedule (Mattenstahlliste), and rebar schemas in this structural drawing.
Report ONLY issues you can directly observe from clearly visible values in the PDF.

CHECK 1 — Pos Coverage in Schemas (pos_coverage)
Cross-reference every Pos number listed in the Stabliste (excluding Pos > 100) with the rebar schemas in the Bewehrung.
Flag any Pos (≤ 100) that exists in the Stabliste but has no corresponding schema drawn on the sheet.
Do NOT flag Pos > 100 in this check.

CHECK 2 — Schema Coverage for All Pos (schema_coverage)
Every distinct Pos in the Stabliste — including the Pos 100+ series — must have at least one bending schema shown.
Flag any Pos (including 100+ series) that lacks any schema representation.
Do NOT flag if a shared group schema explicitly covers the Pos.

CHECK 3 — Mesh Reinforcement Pos (mesh_pos)
If a Mattenstahlliste is present, verify each mesh Pos listed appears in at least one section view.
Do NOT flag if no Mattenstahlliste is visible on the sheet.

CHECK 4 — Mesh-to-Total Mass Ratio (mesh_ratio)
If both Stabliste and Mattenstahlliste are present, calculate:
  ratio = (total_mesh_mass / (total_rebar_mass + total_mesh_mass)) × 100
Flag if ratio < 85 %.
Obtain totals from the "Gesamt" (total) rows of each schedule.
Do NOT flag if either schedule is absent or the totals are not clearly visible.

CHECK 5 — Total Mass Arithmetic (mass_arithmetic)
For each row in the Stabliste (and Mattenstahlliste if present) where ALL four values are clearly visible:
  quantity (n), bar length (m), unit mass (kg/m), shown total mass (kg)
  expected = n × length × unit_mass
Flag if |shown − expected| / expected > 5 %.
Do NOT flag if any required value is missing or unclear.

CHECK 6 — Bending Angle / Mandrel Diameter (bending_angle)
For each rebar schema, verify any explicitly labeled mandrel diameter using these minimum values:
  Ø8  → factor 4, min. dbr = 3.2 cm
  Ø10 → factor 4, min. dbr = 4.0 cm
  Ø12 → factor 4, min. dbr = 4.8 cm
  Ø16 → factor 4, min. dbr = 6.4 cm
  Ø20 → factor 7, min. dbr = 14.0 cm
  Ø24 → factor 7, min. dbr = 16.8 cm
  Ø28 → factor 7, min. dbr = 19.6 cm
Flag if a labeled mandrel diameter in the schema is clearly below the minimum for that bar size.
Do NOT flag unlabeled bending radii or diameters.

CHECK 7 — Bar Length vs Schedule (bar_length)
For each rebar schema where a total length L is explicitly shown, compare it with the "Einzel Länge" in the Stabliste.
Flag if the schema length clearly differs from the schedule value.
Do NOT flag if either value is not explicitly shown.

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       "pos_coverage" | "schema_coverage" | "mesh_pos" | "mesh_ratio" | "mass_arithmetic" | "bending_angle" | "bar_length"
  severity:    "error" for clear non-compliance; "warning" for borderline or ambiguous
  description: concise — quote Pos number, computed vs shown value, or ratio result
  page:        1
  location:    specific location (e.g. "Stabliste row Pos 12" or "Bewehrung Schnitt 3-3")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65

RULES:
  • Only report what is directly visible and unambiguous in the drawing.
  • Do NOT infer or estimate values not shown.
  • If no issues are found for all checks, return an empty list — that is correct.\
"""

# Python generates pass/fail summaries — LLM never needs to produce them.
_CHECK_META: dict[str, tuple[str, str]] = {
    "pos_coverage": (
        "Pos Coverage (≤100)",
        "PASS — all Stabliste positions (≤100) have a corresponding schema.",
    ),
    "schema_coverage": (
        "Schema Coverage (All Pos)",
        "PASS — all Pos including 100+ series have at least one schema.",
    ),
    "mesh_pos": (
        "Mesh Reinforcement Pos",
        "PASS — all mesh positions appear in section views.",
    ),
    "mesh_ratio": (
        "Mesh-to-Total Mass Ratio",
        "PASS — mesh reinforcement ratio ≥ 85 %.",
    ),
    "mass_arithmetic": (
        "Total Mass Arithmetic",
        "PASS — bar schedule mass arithmetic verified correct.",
    ),
    "bending_angle": (
        "Bending Angle / Mandrel Diameter",
        "PASS — all labeled mandrel diameters comply with minimum requirements.",
    ),
    "bar_length": (
        "Bar Length vs Schedule",
        "PASS — all schema lengths match Einzel Länge in Stabliste.",
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
    check: str = Field(description="pos_coverage | schema_coverage | mesh_pos | mesh_ratio | mass_arithmetic | bending_angle | bar_length")
    severity: str = Field(description="error | warning")
    description: str
    page: int
    location: str
    confidence: float = Field(description="0.65–1.0")


class _BendResult(BaseModel):
    issues: list[_BendIssue]  # required — no default so missing field raises ValidationError


def bend_check(state: GraphState) -> dict:
    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_BendResult).with_retry(stop_after_attempt=2)

    result: _BendResult = llm.invoke(  # type: ignore[assignment]
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
        config={"callbacks": [_UsageCallback("bend_check")]},
    )
    print(f"[usage][bend_check] raw items from LLM: {len(result.issues)}")

    # Group LLM findings by check category, filter low-confidence
    by_check: dict[str, list[_BendIssue]] = {k: [] for k in _CHECK_META}
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
