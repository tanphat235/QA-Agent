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
Inspect reinforcement elements, spacers, pin bars, and clamps in this precast wall structural drawing.
Report ONLY issues you can directly observe from visible annotations and dimensions in the PDF.

CHECK 1 — Spacer / Clamp Label Suffix (spacer_label)
Identify all spacer (Abstandhalter) and clamp reinforcement elements in the drawing.
Flag any spacer or clamp whose label does NOT end with the suffix "-M.E.".
Correct examples: "Ø8-M.E.", "Pos 5-M.E.".
Do NOT flag rebar elements that are not spacers or clamps.

CHECK 2 — Vertical Pin Width (pin_width_vertical)
For each vertical pin (vertical stirrup) visible in the section views, verify its width using:
  Required width = wall_width – 2 × Cv
  where wall_width = total wall thickness (from title block or dimension), Cv = concrete cover from the detail view.
Flag if the labeled pin width clearly differs from the required calculated value.
Do NOT flag if wall_width, Cv, or the labeled pin dimension is not explicitly shown.

CHECK 3 — Horizontal Pin Width (pin_width_horizontal)
For each horizontal pin in the section views, verify its width using:
  Required width = wall_width – 2 × Cv – 2 × Ø_layer1   (round down to nearest mm)
  where Ø_layer1 = diameter of the outermost rebar layer (read from the side section label,
  e.g. position 12 → Ø12 → 1.2 cm).
  Example: wall_width=30, Cv=2.5, Ø_layer1=1.2 → 30 – 5.0 – 2.4 = 22.6 → 22 cm
Flag if the labeled horizontal pin width clearly differs from the calculated value.
Do NOT flag if any required dimension is not explicitly shown.

CHECK 4 — Spacer / Clamp Width (spacer_width)
For each spacer or clamp element, verify its width using:
  Required width = wall_width – 2 × Cv + 2 × Ø_spacer   (round up to nearest mm)
  where Ø_spacer = physical diameter of the spacer/clamp wire or element.
  Example: wall_width=30, Cv=2.5, Ø_spacer=0.8 → 30 – 5.0 + 1.6 = 26.6 → 27 cm
Flag if the labeled spacer/clamp width clearly differs from the calculated value.
Do NOT flag if any required dimension is not explicitly shown.

═══════════════════════════════════
OUTPUT FORMAT — one item per finding
═══════════════════════════════════
  check:       "spacer_label" | "pin_width_vertical" | "pin_width_horizontal" | "spacer_width"
  severity:    "error" for missing/wrong label or incorrect dimension causing fabrication risk; "warning" for ambiguous
  description: concise — quote label text, or state: formula, calculated value, and declared value
  page:        1
  location:    specific location (e.g. "Schnitt 6-6, bottom spacer" or "wall side section, horizontal pin Pos 14")
  confidence:  0.65–1.0 — omit the item entirely if confidence is below 0.65

RULES:
  • Only report issues directly visible and unambiguous.
  • When flagging a dimension issue, state the formula and both values in the description.
  • If no issues are found for all checks, return an empty list — that is correct.\
"""

# Python generates pass/fail summaries — LLM never needs to produce them.
_CHECK_META: dict[str, tuple[str, str]] = {
    "spacer_label": (
        "Spacer / Clamp Label Suffix",
        'PASS — all spacer and clamp labels include the "-M.E." suffix.',
    ),
    "pin_width_vertical": (
        "Vertical Pin Width",
        "PASS — all vertical pin widths match wall_width – 2×Cv.",
    ),
    "pin_width_horizontal": (
        "Horizontal Pin Width",
        "PASS — all horizontal pin widths match wall_width – 2×Cv – 2×Ø_layer1.",
    ),
    "spacer_width": (
        "Spacer / Clamp Width",
        "PASS — all spacer/clamp widths match wall_width – 2×Cv + 2×Ø_spacer.",
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


def rebar_check(state: GraphState) -> dict:
    pdf_data: str = state["pdf_data"]  # type: ignore[assignment]

    llm = ChatAnthropic(  # type: ignore[call-arg]
        model="claude-sonnet-4-5",  # type: ignore[call-arg]
        temperature=0,
        max_tokens=4096,  # type: ignore[call-arg]
    ).with_structured_output(_RebarResult).with_retry(stop_after_attempt=2)

    result: _RebarResult = llm.invoke(  # type: ignore[assignment]
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
        config={"callbacks": [_UsageCallback("rebar_check")]},
    )
    print(f"[usage][rebar_check] raw items from LLM: {len(result.issues)}")

    # Group LLM findings by check category, filter low-confidence
    by_check: dict[str, list[_RebarIssue]] = {k: [] for k in _CHECK_META}
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
