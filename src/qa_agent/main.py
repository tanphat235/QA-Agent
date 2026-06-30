import sys
from collections.abc import AsyncIterator
from typing import Any

from dotenv import load_dotenv

from qa_agent.graph import graph

load_dotenv()

_ALL_CHECKS = ["spell", "bend", "rebar"]


async def stream_analysis(
    pdf_path: str,
    enabled_checks: list[str] | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """Run the QA graph and yield each completed node's name and output."""
    checks = enabled_checks if enabled_checks else _ALL_CHECKS
    init: dict[str, Any] = {"pdf_path": pdf_path, "enabled_checks": checks}
    async for event in graph.astream(init):
        node_name = next(iter(event))
        yield node_name, event[node_name]


def main(pdf_path: str = "") -> dict:
    final_state = graph.invoke({"pdf_path": pdf_path, "enabled_checks": _ALL_CHECKS})
    result = final_state["ui_response"]
    print(result)
    return result


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else ""
    main(path)
