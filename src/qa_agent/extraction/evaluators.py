"""Deterministic evaluators for user-defined checks (Python, no LLM)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from qa_agent.extraction.context import ExtractionContext
from qa_agent.extraction.debug_trace import log_check_trace, log_scale_values
from qa_agent.extraction.element_code import resolve_drawing_codes
from qa_agent.extraction.scale import resolve_scales
from qa_agent.state import GraphState


@dataclass
class DeterministicIssue:
    check: str
    severity: str
    description: str
    page: int = 1
    location: str = ""
    confidence: float = 1.0


@dataclass
class DeterministicResult:
    issues: list[DeterministicIssue] = field(default_factory=list)
    not_found: bool = False


def _eval_drawing_code(state: GraphState, ctx: ExtractionContext) -> DeterministicResult:
    top, from_title = resolve_drawing_codes(ctx.title_block, ctx.drawing_raw_text)

    if not top or not from_title:
        print(
            f"[extraction][drawing_code] NOT FOUND — top_left={top!r} title_suffix={from_title!r} "
            f"drawing_title={ctx.title_block.get('drawing_title_value')!r}"
        )
        return DeterministicResult(not_found=True)

    if top.upper() == from_title.upper():
        print(f"[extraction][drawing_code] PASS: {top!r} == {from_title!r}")
        return DeterministicResult()

    print(f"[extraction][drawing_code] FAIL: {top!r} != {from_title!r}")
    return DeterministicResult(issues=[
        DeterministicIssue(
            check="drawing_code",
            severity="error",
            description=(
                f"Drawing code mismatch: top-left label={top}, "
                f"Drawing Title suffix={from_title}"
            ),
            location="title block / top-left label",
        ),
    ])


def _eval_scale_check(state: GraphState, ctx: ExtractionContext) -> DeterministicResult:
    resolved = resolve_scales(ctx.title_block, ctx.drawing_raw_text)
    allowed: list[str] = resolved.get("title_blocks") or []
    title_scale = resolved["title_block"]
    sections: list[dict] = resolved["sections"]
    allowed_set = set(allowed)

    log_scale_values("scale_check", title_scales=allowed, sections=sections)
    log_check_trace(
        "scale_check",
        phase="evaluate",
        inputs={
            "title_block_scales": allowed,
            "title_block_scale": title_scale,
            "section_count": len(sections),
        },
        details={
            "sections": sections,
            "title_block_field": ctx.title_block.get("scale_title_block"),
            "title_blocks_field": ctx.title_block.get("scale_title_blocks"),
        },
    )

    if not allowed:
        log_check_trace("scale_check", phase="evaluate", result="NOT FOUND (no title block scale)")
        return DeterministicResult(not_found=True)

    if not sections:
        log_check_trace("scale_check", phase="evaluate", result="NOT FOUND (no section scales)")
        return DeterministicResult(not_found=True)

    mismatches = [s for s in sections if s.get("scale") not in allowed_set]
    if not mismatches:
        log_check_trace(
            "scale_check",
            phase="evaluate",
            result=f"PASS (all {len(sections)} section scale(s) in title block {allowed!r})",
        )
        print(f"[extraction][scale_check] PASS: all sections in title block scales {allowed!r}")
        return DeterministicResult()

    log_check_trace(
        "scale_check",
        phase="evaluate",
        result=f"FAIL ({len(mismatches)} section scale(s) not in title block {allowed!r})",
        details={"mismatches": mismatches},
    )
    print(f"[extraction][scale_check] FAIL: {len(mismatches)} section scale(s) not in {allowed!r}")
    issues = [
        DeterministicIssue(
            check="scale_check",
            severity="error",
            description=(
                f"Scale mismatch: title block allows {', '.join(allowed)}, "
                f"section '{sec.get('label', '')[:60]}'={sec.get('scale')}"
            ),
            location=sec.get("label", "section view")[:80],
        )
        for sec in mismatches
    ]
    return DeterministicResult(issues=issues)


DETERMINISTIC_EVALUATORS: dict[str, Callable[[GraphState, ExtractionContext], DeterministicResult]] = {
    "drawing_code": _eval_drawing_code,
    "scale_check": _eval_scale_check,
}


def run_deterministic_check(
    check_key: str,
    state: GraphState,
    ctx: ExtractionContext,
) -> DeterministicResult | None:
    """Run a registered deterministic evaluator, or None if check has no Python evaluator."""
    fn = DETERMINISTIC_EVALUATORS.get(check_key)
    if fn is None:
        return None
    return fn(state, ctx)
