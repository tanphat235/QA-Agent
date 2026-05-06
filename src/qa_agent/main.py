import sys
from collections.abc import AsyncIterator
from typing import Any

from dotenv import load_dotenv

from qa_agent.graph import graph

load_dotenv()


async def stream_analysis(pdf_path: str) -> AsyncIterator[tuple[str, Any]]:
    """Run the QA graph for ``pdf_path`` and yield each completed node's name and output."""
    async for event in graph.astream({"pdf_path": pdf_path}):
        node_name = next(iter(event))
        yield node_name, event[node_name]


def main(pdf_path: str = "sample.pdf") -> dict:
    final_state = graph.invoke({"pdf_path": pdf_path})
    result = final_state["ui_response"]
    print(result)
    return result


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "sample.pdf"
    main(path)
