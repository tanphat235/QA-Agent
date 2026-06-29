"""Deterministic evaluators for user-defined checks (Python, no LLM)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from qa_agent.extraction.context import ExtractionContext
from qa_agent.extraction.element_code import resolve_drawing_codes
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


DETERMINISTIC_EVALUATORS: dict[str, Callable[[GraphState, ExtractionContext], DeterministicResult]] = {
    "drawing_code": _eval_drawing_code,
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
