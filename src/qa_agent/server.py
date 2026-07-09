import asyncio
import base64
import os
import json
import sys
import tempfile
import traceback
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated
from dotenv import load_dotenv

load_dotenv()


def _configure_stdio_utf8() -> None:
    """Windows consoles often default to cp1252; avoid UnicodeEncodeError in logs."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _log(msg: str) -> None:
    """Print a log line without ever raising UnicodeEncodeError."""
    text = str(msg)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(enc, errors="replace").decode(enc), flush=True)


_configure_stdio_utf8()

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from qa_agent.graph import graph
from qa_agent.nodes.pdf_extractor import extract_steel_list_pdf, extract_overview_plan_pdf
from qa_agent.pdf_annotator import annotate_pdf
from qa_agent import checks_registry as registry

LANGGRAPH_URL = os.getenv("LANGGRAPH_URL", "http://127.0.0.1:2024")
GRAPH_NAME = "qa_agent"


def _use_langgraph_api() -> bool:
    """Use remote LangGraph API server only when explicitly enabled (local dev + Studio)."""
    return os.getenv("QA_USE_LANGGRAPH_API", "false").lower() in ("true", "1", "yes")


def _langgraph_is_remote() -> bool:
    url = (LANGGRAPH_URL or "").lower()
    return not any(host in url for host in ("127.0.0.1", "localhost"))

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


def _node_sse_events(node_name: str, node_data: dict) -> tuple[list[str], dict | None]:
    """Convert a completed node into SSE event strings.

    Returns (events, ui_response) when return_to_ui produced a report.
    """
    label = NODE_LABELS.get(node_name, node_name)
    events = [_sse({"type": "progress", "node": node_name, "label": label})]
    _log(f"[server] OK node: {node_name}  |  keys: {list(node_data.keys()) if isinstance(node_data, dict) else type(node_data)}")

    if node_name != "return_to_ui":
        return events, None

    ui_response = node_data.get("ui_response") if isinstance(node_data, dict) else None
    _log(f"[server] ui_response summary: {ui_response.get('summary') if ui_response else 'NONE'}")
    if ui_response:
        events.append(_sse({"type": "result", "data": ui_response}))
    return events, ui_response


def _ui_from_state_payload(payload: object) -> dict | None:
    """Extract ui_response from LangGraph thread/run state payloads."""
    if not isinstance(payload, dict):
        return None
    direct = payload.get("ui_response")
    if isinstance(direct, dict):
        return direct
    values = payload.get("values")
    if isinstance(values, dict):
        nested = values.get("ui_response")
        if isinstance(nested, dict):
            return nested
    return None


async def _recover_ui_response(lg, thread_id: str, run_id: str | None) -> dict | None:
    """Best-effort fetch of the final report when the live stream drops early."""
    try:
        thread_state = await lg.threads.get_state(thread_id)
        ui = _ui_from_state_payload(thread_state)
        if ui:
            _log("[server] recovered ui_response via threads.get_state")
            return ui
    except Exception as exc:
        _log(f"[server] WARN threads.get_state failed (non-fatal): {exc}")

    if not run_id:
        return None

    try:
        joined = await lg.runs.join(thread_id, run_id)
        ui = _ui_from_state_payload(joined)
        if ui:
            _log("[server] recovered ui_response via runs.join")
            return ui
    except Exception as exc:
        _log(f"[server] WARN runs.join failed (non-fatal): {exc}")

    return None


async def _create_thread_id(lg) -> str:
    """Create a LangGraph thread; required for runs but isolated from monitoring."""
    thread = await lg.threads.create()
    return thread["thread_id"]


def _monitoring_sse(thread_id: str) -> str | None:
    """Optional Studio/monitoring metadata for LangSmith — must never break the run."""
    try:
        studio_url = f"https://smith.langchain.com/studio/?baseUrl={LANGGRAPH_URL}"
        _log(f"[server] thread_id : {thread_id}")
        _log(f"[server] studio    : {studio_url}")
        return _sse({"type": "run_started", "thread_id": thread_id, "studio_url": studio_url})
    except Exception as exc:
        _log(f"[server] WARN monitoring metadata skipped (non-fatal): {exc}")
        return None


async def _run_graph_inprocess(
    tmp_path: str,
    enabled_checks: list[str],
    enabled_sub_checks: dict[str, list[str]] | None = None,
    steel_list_data: dict | None = None,
    overview_plan_data: dict | None = None,
) -> AsyncIterator[str]:
    """Run the compiled graph inside the FastAPI process (production default)."""
    _log("[server] Running graph in-process (no LangGraph API server)")

    graph_input: dict = {
        "pdf_path": tmp_path,
        "enabled_checks": enabled_checks,
    }
    if enabled_sub_checks:
        graph_input["enabled_sub_checks"] = enabled_sub_checks
    if steel_list_data:
        graph_input["steel_list_data"] = steel_list_data
    if overview_plan_data:
        graph_input["overview_plan_data"] = overview_plan_data

    got_result = False
    try:
        async for event in graph.astream(graph_input, stream_mode="updates"):
            for node_name, node_data in event.items():
                events, ui_response = _node_sse_events(node_name, node_data)
                for item in events:
                    yield item
                if ui_response:
                    got_result = True
    except Exception as exc:
        _log(f"[server] ERR in-process graph failed: {exc}")
        traceback.print_exc()
        yield _sse({"type": "error", "message": str(exc)})
        return

    if not got_result:
        yield _sse({"type": "error", "message": "Graph finished without ui_response"})


async def _run_graph_via_api(
    pdf_bytes: bytes,
    tmp_path: str,
    enabled_checks: list[str],
    enabled_sub_checks: dict[str, list[str]] | None = None,
    steel_list_data: dict | None = None,
    overview_plan_data: dict | None = None,
) -> AsyncIterator[str]:
    """Stream SSE events via remote LangGraph API (opt-in local dev only)."""
    from langgraph_sdk import get_client

    lg = get_client(url=LANGGRAPH_URL)

    try:
        thread_id = await _create_thread_id(lg)
    except Exception as exc:
        _log(f"[server] ERR could not create LangGraph thread: {exc}")
        yield _sse({"type": "error", "message": f"Could not start LangGraph run: {exc}"})
        return

    # LangSmith Studio link — optional; failures here must not abort analysis.
    monitoring = _monitoring_sse(thread_id)
    if monitoring:
        yield monitoring

    remote = _langgraph_is_remote()
    graph_input: dict = {
        "pdf_path": "" if remote else tmp_path,
        "pdf_data": base64.b64encode(pdf_bytes).decode("ascii"),
        "enabled_checks": enabled_checks,
    }
    if enabled_sub_checks:
        graph_input["enabled_sub_checks"] = enabled_sub_checks
    if steel_list_data:
        graph_input["steel_list_data"] = steel_list_data
    if overview_plan_data:
        graph_input["overview_plan_data"] = overview_plan_data

    got_result = False
    run_id: str | None = None
    stream_error: str | None = None

    try:
        async for chunk in lg.runs.stream(
            thread_id,
            GRAPH_NAME,
            input=graph_input,
            stream_mode="updates",
        ):
            if chunk.event == "metadata":
                rid = chunk.data.get("run_id") if isinstance(chunk.data, dict) else None
                if rid:
                    run_id = rid
                    _log(f"[server] run_id    : {run_id}")
            elif chunk.event == "updates":
                for node_name, node_data in chunk.data.items():
                    events, ui_response = _node_sse_events(node_name, node_data)
                    for event in events:
                        yield event
                    if ui_response:
                        got_result = True
            elif chunk.event == "error":
                stream_error = str(chunk.data)
                _log(f"[server] WARN LangGraph stream error (will try recovery): {chunk.data}")
    except Exception as exc:
        stream_error = str(exc)
        _log(f"[server] WARN LangGraph stream interrupted (will try recovery): {exc}")

    if not got_result:
        ui_response = await _recover_ui_response(lg, thread_id, run_id)
        if ui_response:
            yield _sse({"type": "progress", "node": "return_to_ui", "label": NODE_LABELS["return_to_ui"]})
            yield _sse({"type": "result", "data": ui_response})
            got_result = True

    if not got_result and stream_error:
        yield _sse({"type": "error", "message": stream_error})


async def _run_graph(
    pdf_bytes: bytes,
    tmp_path: str,
    enabled_checks: list[str],
    enabled_sub_checks: dict[str, list[str]] | None = None,
    steel_list_data: dict | None = None,
    overview_plan_data: dict | None = None,
) -> AsyncIterator[str]:
    if _use_langgraph_api():
        async for event in _run_graph_via_api(
            pdf_bytes, tmp_path, enabled_checks, enabled_sub_checks,
            steel_list_data, overview_plan_data,
        ):
            yield event
        return

    async for event in _run_graph_inprocess(
        tmp_path, enabled_checks, enabled_sub_checks, steel_list_data, overview_plan_data,
    ):
        yield event


@app.post("/api/analyze")
async def analyze(
    file: Annotated[UploadFile, File()],
    checks: Annotated[str, Form()] = "spell,bend,rebar",
    sub_checks: Annotated[str, Form()] = "{}",
    steel_list: Annotated[UploadFile | None, File()] = None,
    overview_plan: Annotated[UploadFile | None, File()] = None,
):
    enabled_checks = [c.strip() for c in checks.split(",") if c.strip() in _ALL_CHECKS] or _ALL_CHECKS[:]

    try:
        enabled_sub_checks: dict[str, list[str]] = json.loads(sub_checks) if sub_checks else {}
    except (json.JSONDecodeError, ValueError):
        enabled_sub_checks = {}

    data = await file.read()
    tmp_path = await _save_upload(data)

    _log(f"\n[server] === New analysis: {file.filename} -> {tmp_path} | checks: {enabled_checks} | sub_checks: {enabled_sub_checks} ===")
    if _use_langgraph_api():
        _log(f"[server] Routing to LangGraph API at {LANGGRAPH_URL}")
    else:
        _log("[server] Graph mode: in-process")

    # ── pdfplumber pre-extraction for supplementary files ───────────────────
    steel_list_data: dict | None = None
    overview_plan_data: dict | None = None

    if steel_list and steel_list.filename:
        sl_bytes = await steel_list.read()
        sl_tmp = await _save_upload(sl_bytes)
        try:
            steel_list_data = await asyncio.to_thread(extract_steel_list_pdf, sl_tmp)
            # Carry the raw PDF (base64) so checks can read the table from the
            # rendered document (vision) — pdfplumber text loses cells like the
            # Korrosionsschutz "FV" code that sit in narrow/wrapped columns.
            steel_list_data["pdf_data"] = base64.b64encode(sl_bytes).decode("ascii")
            _log(f"[server] steel_list extracted: gesamtmasse={steel_list_data.get('gesamtmasse')!r}  pages={steel_list_data.get('page_count')}")
        except Exception as exc:
            _log(f"[server] ERR steel_list extraction failed: {exc}")
        finally:
            try:
                os.unlink(sl_tmp)
            except OSError:
                pass

    if overview_plan and overview_plan.filename:
        op_bytes = await overview_plan.read()
        op_tmp = await _save_upload(op_bytes)
        try:
            overview_plan_data = await asyncio.to_thread(extract_overview_plan_pdf, op_tmp)
            _log(f"[server] overview_plan extracted: pages={overview_plan_data.get('page_count')}  chars={len(overview_plan_data.get('raw_text', ''))}")
        except Exception as exc:
            _log(f"[server] ERR overview_plan extraction failed: {exc}")
        finally:
            try:
                os.unlink(op_tmp)
            except OSError:
                pass

    async def stream():
        yield _sse({"type": "ack"})
        try:
            async for event in _run_graph(
                data, tmp_path, enabled_checks, enabled_sub_checks, steel_list_data, overview_plan_data
            ):
                yield event
        except Exception as exc:
            _log(f"[server] ERR EXCEPTION: {exc}")
            traceback.print_exc()
            yield _sse({"type": "error", "message": str(exc)})
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            _log("[server] === Analysis done ===\n")

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/annotate")
async def annotate_report(
    file: Annotated[UploadFile, File()],
    result: Annotated[str, Form()],
):
    """Return the uploaded PDF annotated with the failed findings from `result`.

    `result` is the analysis-result JSON the frontend already holds. Only real
    findings (ERROR/WARNING, not per-check summaries or not-found items) are
    annotated — each anchored where its offending text appears in the drawing.
    """
    pdf_bytes = await file.read()
    try:
        parsed = json.loads(result) if result else {}
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid result JSON")

    sections = parsed.get("sections") if isinstance(parsed, dict) else None
    issues: list[dict] = []
    for section in (sections or []):
        if not isinstance(section, dict):
            continue
        current_check = section.get("title")
        for it in (section.get("issues") or []):
            if not isinstance(it, dict):
                continue
            # Per-check summary / not-found item — remember its name, don't annotate.
            if "passed" in it or it.get("not_found") is True:
                current_check = it.get("check_name") or current_check
                continue
            sev = str(it.get("severity", "")).upper()
            if sev not in ("ERROR", "WARNING"):
                continue
            issues.append({
                "page":        it.get("page", 1),
                "description": it.get("description", ""),
                "location":    it.get("location", ""),
                "severity":    sev,
                "check_name":  it.get("check_name") or current_check or it.get("category"),
                "category":    it.get("category"),
            })

    _log(f"[annotate] {len(issues)} failed finding(s) -> annotating {file.filename!r}")
    try:
        annotated = await asyncio.to_thread(annotate_pdf, pdf_bytes, issues)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Annotation failed: {exc}")

    base = (file.filename or "drawing.pdf").rsplit(".", 1)[0]
    return Response(
        content=annotated,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{base}_annotated.pdf"'},
    )


@app.get("/api/extraction-fields")
async def extraction_fields():
    """Catalog of pdfplumber fields available to user-defined checks (for frontend)."""
    from qa_agent.extraction import list_extraction_fields
    return {"fields": await asyncio.to_thread(list_extraction_fields)}


@app.get("/api/checks")
async def list_checks():
    """All defined checks (built-in + custom), for the Define-Rules UI and the
    dynamic check-selection sidebar."""
    checks = await asyncio.to_thread(registry.list_checks)
    domains = [
        {
            "key": d,
            "title": registry.domain_title(d),
            "coming_soon": d in registry.COMING_SOON_DOMAINS,
        }
        for d in registry.ALL_DOMAINS
    ]
    return {"checks": checks, "domains": domains}


class _CheckBody(BaseModel):
    domain: str = "spell"
    key: str | None = None
    display_name: str
    description: str = ""
    prompt: str = ""
    pass_text: str = "PASS"
    not_found_text: str = "NOT FOUND"
    requires_vision: bool = False


@app.post("/api/checks")
async def save_check(body: _CheckBody):
    try:
        saved = await asyncio.to_thread(
            registry.save_check,
            domain=body.domain, key=body.key, display_name=body.display_name,
            description=body.description, prompt=body.prompt,
            pass_text=body.pass_text, not_found_text=body.not_found_text,
            requires_vision=body.requires_vision,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        _log(f"[server] ERR save_check filesystem: {exc}")
        raise HTTPException(status_code=500, detail=f"Could not save check: {exc}")
    return {"ok": True, "check": saved}


@app.delete("/api/checks/{domain}/{key}")
async def delete_check(domain: str, key: str):
    try:
        await asyncio.to_thread(registry.delete_check, domain, key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}
