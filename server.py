"""Vercel entrypoint — exposes the FastAPI app from src/qa_agent/server.py."""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from qa_agent.server import app  # noqa: F401
