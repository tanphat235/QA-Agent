import os
import json
import tempfile
import traceback
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from qa_agent.graph import graph

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


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    print(f"\n[server] === New analysis request: {file.filename} → {tmp_path} ===")

    async def stream():
        yield _sse({"type": "ack"})
        try:
            async for event in graph.astream({"pdf_path": tmp_path}):
                node_name = next(iter(event))
                node_data  = event[node_name]
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
