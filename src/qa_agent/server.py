import asyncio
import os
import json
import tempfile
import traceback
from collections.abc import AsyncIterator
from typing import Annotated
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langgraph_sdk import get_client

from qa_agent.mistakes_store import load_structured, save_structured

LANGGRAPH_URL = os.getenv("LANGGRAPH_URL", "http://127.0.0.1:2024")
GRAPH_NAME = "qa_agent"

app = FastAPI(title="Drawing Analyzer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

NODE_LABELS: dict[str, str] = {
    "preprocess":        "Extracting PDF content",
    "spell_check":       "Checking spelling & labels",
    "bend_check":        "Validating bending details",
    "rebar_check":       "Validating rebar specifications",
    "aggregate_results": "Aggregating results",
    "return_to_ui":      "Preparing report",
}

_ALL_CHECKS = ["spell", "bend", "rebar"]


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _save_upload(data: bytes) -> str:
    """Write upload bytes to a temp file without blocking the event loop."""
    def _write() -> str:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(data)
            return tmp.name
    return await asyncio.to_thread(_write)


def _node_sse_events(node_name: str, node_data: dict) -> list[str]:
    """Convert a completed node into SSE event strings."""
    label = NODE_LABELS.get(node_name, node_name)
    events = [_sse({"type": "progress", "node": node_name, "label": label})]
    print(f"[server] ✓ node: {node_name}  |  keys: {list(node_data.keys()) if isinstance(node_data, dict) else type(node_data)}")

    if node_name != "return_to_ui":
        return events

    ui_response = node_data.get("ui_response") if isinstance(node_data, dict) else None
    print(f"[server] ui_response summary: {ui_response.get('summary') if ui_response else 'NONE'}")
    if ui_response:
        events.append(_sse({"type": "result", "data": ui_response}))
    return events


async def _run_graph(tmp_path: str, enabled_checks: list[str]) -> AsyncIterator[str]:
    """Stream SSE events by routing graph execution through LangGraph API."""
    lg = get_client(url=LANGGRAPH_URL)
    thread = await lg.threads.create()
    thread_id = thread["thread_id"]
    studio_url = f"https://smith.langchain.com/studio/?baseUrl={LANGGRAPH_URL}"
    print(f"[server] thread_id : {thread_id}")
    print(f"[server] studio    : {studio_url}")

    yield _sse({"type": "run_started", "thread_id": thread_id, "studio_url": studio_url})

    async for chunk in lg.runs.stream(
        thread_id,
        GRAPH_NAME,
        input={"pdf_path": tmp_path, "enabled_checks": enabled_checks},
        stream_mode="updates",
    ):
        if chunk.event == "metadata":
            run_id = chunk.data.get("run_id") if isinstance(chunk.data, dict) else None
            if run_id:
                print(f"[server] run_id    : {run_id}")
        elif chunk.event == "updates":
            for node_name, node_data in chunk.data.items():
                for event in _node_sse_events(node_name, node_data):
                    yield event
        elif chunk.event == "error":
            print(f"[server] ✗ LangGraph error: {chunk.data}")
            yield _sse({"type": "error", "message": str(chunk.data)})


@app.post("/api/analyze")
async def analyze(
    file: Annotated[UploadFile, File()],
    checks: Annotated[str, Form()] = "spell,bend,rebar",
):
    enabled_checks = [c.strip() for c in checks.split(",") if c.strip() in _ALL_CHECKS] or _ALL_CHECKS[:]

    data = await file.read()
    tmp_path = await _save_upload(data)

    print(f"\n[server] === New analysis: {file.filename} → {tmp_path} | checks: {enabled_checks} ===")
    print(f"[server] Routing to LangGraph API at {LANGGRAPH_URL}")

    async def stream():
        yield _sse({"type": "ack"})
        try:
            async for event in _run_graph(tmp_path, enabled_checks):
                yield event
        except Exception as exc:
            print(f"[server] ✗ EXCEPTION: {exc}")
            traceback.print_exc()
            yield _sse({"type": "error", "message": str(exc)})
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            print("[server] === Analysis done ===\n")

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/mistakes-structured")
async def get_mistakes_structured():
    data = await asyncio.to_thread(load_structured)
    return data


class _MistakesStructuredBody(BaseModel):
    data: dict


@app.post("/api/mistakes-structured")
async def save_mistakes_structured(body: _MistakesStructuredBody):
    try:
        await asyncio.to_thread(save_structured, body.data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True}
