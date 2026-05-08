import base64
import logging
from anthropic import Anthropic
from pypdf import PdfReader

from qa_agent.state import GraphState

logger = logging.getLogger(__name__)

_COMMON_SYSTEM = """\
You are a senior structural rebar detailing QA reviewer performing a visual and technical inspection of a PDF structural drawing.
German terminology: "Schnitt X-X" = section view, "Pos" = bar position/mark, "Gesamt" = total, "Stahl" = steel, \
"Maßstab" / "M 1:XX" = scale, "Ansicht" = elevation, "Detail" = detail view.\
"""

_VALIDATION_PROMPT = """\
Validate whether this PDF is acceptable for a rebar detailing QA pipeline.

Requirements:
- The PDF must contain exactly one readable drawing sheet.
- The drawing must clearly be a structural rebar detailing drawing.
- Reject unrelated PDFs such as reports, contracts, architectural-only drawings, \
MEP drawings, invoices, blank scans, or image placeholders.
- Reject drawings that are unreadable, heavily cropped, or too blurry.

Return ONLY one of the following formats:

VALID

or

INVALID: <short reason>

Do not include anything else.\
"""


def preprocess(state: GraphState) -> dict:
    pdf_path = state["pdf_path"]

    # ── Code-based checks ──────────────────────────────────────────
    reader = PdfReader(pdf_path)
    page_count = len(reader.pages)
    if page_count != 1:
        raise ValueError(
            f"Invalid PDF: expected exactly 1 page, got {page_count}. "
            "Please upload a single-sheet drawing."
        )

    # ── Encode once — stored in state so downstream nodes skip disk I/O ──
    with open(pdf_path, "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    # ── LLM-based validation — warms the prompt cache for QA nodes ────
    client = Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=256,
        system=_COMMON_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data,
                        },
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": _VALIDATION_PROMPT},
                ],
            }
        ],
    )

    u = response.usage
    print(
        f"[usage][preprocess] input={u.input_tokens}"
        f"  cache_create={getattr(u, 'cache_creation_input_tokens', 0) or 0}"
        f"  cache_read={getattr(u, 'cache_read_input_tokens', 0) or 0}"
        f"  output={u.output_tokens}"
    )

    verdict: str = response.content[0].text.strip()  # type: ignore[union-attr]

    if not verdict.startswith("VALID"):
        reason = verdict.removeprefix("INVALID:").strip() if "INVALID:" in verdict else verdict
        raise ValueError(f"PDF rejected: {reason}")

    return {"page_count": page_count, "pdf_data": pdf_data}
