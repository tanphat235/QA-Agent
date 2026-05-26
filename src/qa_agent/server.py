import asyncio
import os
import json
import tempfile
import traceback
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated
from dotenv import load_dotenv

import docx as python_docx

load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from langgraph_sdk import get_client

from qa_agent.mistakes_store import load_structured, save_structured

LANGGRAPH_URL = os.getenv("LANGGRAPH_URL", "http://127.0.0.1:2024")

_KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "QA AI Drawing" / "QA Knowledge"
_DOCX_PATH     = _KNOWLEDGE_DIR / "structural_qa_rag_knowledge_pack.docx"
_RAG_CACHE_PATH = Path(__file__).parent / "rag" / "data" / "knowledge_cache.json"

# Domain-section keywords (same as knowledge_builder.py)
_DOMAIN_KEYWORDS = {
    "spell": ["spell check node"],
    "bend":  ["bend check node"],
    "rebar": ["rebar check node"],
}
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


async def _run_graph(
    tmp_path: str,
    enabled_checks: list[str],
    enabled_sub_checks: dict[str, list[str]] | None = None,
) -> AsyncIterator[str]:
    """Stream SSE events by routing graph execution through LangGraph API."""
    lg = get_client(url=LANGGRAPH_URL)
    thread = await lg.threads.create()
    thread_id = thread["thread_id"]
    studio_url = f"https://smith.langchain.com/studio/?baseUrl={LANGGRAPH_URL}"
    print(f"[server] thread_id : {thread_id}")
    print(f"[server] studio    : {studio_url}")

    yield _sse({"type": "run_started", "thread_id": thread_id, "studio_url": studio_url})

    graph_input: dict = {"pdf_path": tmp_path, "enabled_checks": enabled_checks}
    if enabled_sub_checks:
        graph_input["enabled_sub_checks"] = enabled_sub_checks

    async for chunk in lg.runs.stream(
        thread_id,
        GRAPH_NAME,
        input=graph_input,
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
    sub_checks: Annotated[str, Form()] = "{}",
):
    enabled_checks = [c.strip() for c in checks.split(",") if c.strip() in _ALL_CHECKS] or _ALL_CHECKS[:]

    try:
        enabled_sub_checks: dict[str, list[str]] = json.loads(sub_checks) if sub_checks else {}
    except (json.JSONDecodeError, ValueError):
        enabled_sub_checks = {}

    data = await file.read()
    tmp_path = await _save_upload(data)

    print(f"\n[server] === New analysis: {file.filename} → {tmp_path} | checks: {enabled_checks} | sub_checks: {enabled_sub_checks} ===")
    print(f"[server] Routing to LangGraph API at {LANGGRAPH_URL}")

    async def stream():
        yield _sse({"type": "ack"})
        try:
            async for event in _run_graph(tmp_path, enabled_checks, enabled_sub_checks):
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


@app.get("/api/knowledge-base/download")
async def download_knowledge_file():
    def _ensure() -> None:
        _KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        if not _DOCX_PATH.exists():
            doc = python_docx.Document()
            doc.add_heading("QA Knowledge Base", level=1)
            for heading in ("Spell Check Node", "Bend Check Node", "Rebar Check Node"):
                doc.add_heading(heading, level=2)
                doc.add_paragraph("Add your QA rules here.")
            doc.save(str(_DOCX_PATH))

    await asyncio.to_thread(_ensure)
    return FileResponse(
        path=str(_DOCX_PATH),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="structural_qa_rag_knowledge_pack.docx",
    )


_SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


@app.post("/api/knowledge-base/upload")
async def upload_knowledge_file(file: Annotated[UploadFile, File()]):
    import base64  # noqa: PLC0415

    data = await file.read()

    def _save_and_index() -> tuple[int, int]:
        _KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        _DOCX_PATH.write_bytes(data)

        doc = python_docx.Document(str(_DOCX_PATH))

        # ── Build rId → image map from document relationships ──────────────
        rid_to_img: dict[str, dict] = {}
        for rel in doc.part.rels.values():
            if "image" not in rel.reltype:
                continue
            media_type = rel.target_part.content_type
            if media_type not in _SUPPORTED_IMAGE_TYPES:
                continue
            b64 = base64.standard_b64encode(rel.target_part.blob).decode()
            rid_to_img[rel.rId] = {"data": b64, "media_type": media_type}

        # ── Walk paragraphs: extract text + images, split by domain ────────
        text_sections: dict[str, list[str]] = {d: [] for d in ("spell", "bend", "rebar")}
        img_sections:  dict[str, list[dict]] = {d: [] for d in ("spell", "bend", "rebar")}
        current: str | None = None

        for para in doc.paragraphs:
            text = para.text.strip()
            lower = text.lower()
            for domain, keywords in _DOMAIN_KEYWORDS.items():
                if any(kw in lower for kw in keywords):
                    current = domain
                    break
            if not current:
                continue
            if text:
                text_sections[current].append(text)
            for elem in para._element.iter():
                rid = elem.get(_R_EMBED)
                if rid and rid in rid_to_img:
                    img = rid_to_img[rid]
                    if img not in img_sections[current]:   # deduplicate
                        img_sections[current].append(img)

        # Fall back: no domain headers found → assign everything to all domains
        if not any(lines for lines in text_sections.values()):
            all_text = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            all_imgs  = list(rid_to_img.values())
            for domain in ("spell", "bend", "rebar"):
                text_sections[domain] = all_text
                img_sections[domain]  = all_imgs

        cache: dict = {}
        if _RAG_CACHE_PATH.exists():
            with open(_RAG_CACHE_PATH, encoding="utf-8") as f:
                cache = json.load(f)
        cache["docx_knowledge"] = {d: "\n".join(lines) for d, lines in text_sections.items()}
        cache["docx_images"]    = img_sections
        _RAG_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_RAG_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)

        total_imgs = sum(len(v) for v in img_sections.values())
        return sum(len(v) for v in text_sections.values()), total_imgs

    lines, imgs = await asyncio.to_thread(_save_and_index)
    from qa_agent.rag.retriever import _load_cache  # noqa: PLC0415
    _load_cache.cache_clear()
    return {"ok": True, "lines_indexed": lines, "images_indexed": imgs}
