"""Debug trace logging for user-defined checks (console output during analyze)."""
from __future__ import annotations

import json
from typing import Any


def log_check_trace(
    check_key: str,
    *,
    phase: str,
    inputs: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    result: str = "",
) -> None:
    """Print a structured debug block visible in LangGraph / backend logs."""
    print(f"[trace][{check_key}] === DEBUG TRACE ({phase}) ===")
    if inputs:
        try:
            payload = json.dumps(inputs, ensure_ascii=False, indent=2, default=str)
        except TypeError:
            payload = str(inputs)
        print(f"[trace][{check_key}] inputs:\n{payload}")
    if details:
        for k, v in details.items():
            print(f"[trace][{check_key}]   {k}: {v!r}")
    if result:
        print(f"[trace][{check_key}] result: {result}")


def log_scale_values(
    check_key: str,
    *,
    title_scales: list[str] | None = None,
    title_scale: str | None = None,
    sections: list[dict],
) -> None:
    """Dedicated scale_check debug — allowed title-block scales vs each section."""
    allowed = title_scales if title_scales is not None else ([title_scale] if title_scale else [])
    allowed_set = set(allowed)
    print(f"[trace][{check_key}] --- scale values ---")
    print(f"[trace][{check_key}]   title_block_scales (allowed): {allowed!r}")
    if not sections:
        print(f"[trace][{check_key}]   section_scales: (none found)")
        return
    for i, sec in enumerate(sections, 1):
        sec_scale = sec.get("scale")
        if sec_scale in allowed_set:
            flag = "OK"
        elif allowed:
            flag = "MISMATCH"
        else:
            flag = "?"
        print(
            f"[trace][{check_key}]   section[{i}] {flag} "
            f"scale={sec_scale!r} label={sec.get('label')!r} "
            f"(line {sec.get('line')}, {sec.get('source')})"
        )
