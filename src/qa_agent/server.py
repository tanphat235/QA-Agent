import os
import json
import tempfile
import traceback
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from qa_agent.main import stream_analysis

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


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


_ALL_CHECKS = ["spell", "bend", "rebar"]


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    checks: str = Form("spell,bend,rebar"),
):
    enabled_checks = [c.strip() for c in checks.split(",") if c.strip() in _ALL_CHECKS]
    if not enabled_checks:
        enabled_checks = _ALL_CHECKS[:]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    print(f"\n[server] === New analysis request: {file.filename} → {tmp_path} | checks: {enabled_checks} ===")

    async def stream():
        yield _sse({"type": "ack"})
        try:
            async for node_name, node_data in stream_analysis(tmp_path, enabled_checks):
                print(f"[server] ✓ node completed: {node_name}  |  keys: {list(node_data.keys()) if isinstance(node_data, dict) else type(node_data)}")

                label = NODE_LABELS.get(node_name, node_name)
                yield _sse({"type": "progress", "node": node_name, "label": label})

                if node_name == "return_to_ui":
                    ui_response = node_data.get("ui_response") if isinstance(node_data, dict) else None
                    print(f"[server] ui_response summary: {ui_response.get('summary') if ui_response else 'NONE'}")
                    if ui_response:
                        yield _sse({"type": "result", "data": ui_response})

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
