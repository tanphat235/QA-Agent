import base64
from anthropic import Anthropic
from qa_agent.state import GraphState, PDFContent

_PROMPT = """\
Extract all content from this structural drawing PDF verbatim.
Include every label, annotation, rebar mark, bar schedule row, dimension, \
section title, callout, and note exactly as written.

Begin your response with a line in this exact format (replace N with the actual number):
PAGE_COUNT: N

Then output all extracted text with no other commentary.\
"""


def preprocess(state: GraphState) -> dict:
    client = Anthropic()

    with open(state["pdf_path"], "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8096,
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
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    )

    full_text: str = response.content[0].text  # type: ignore[union-attr]

    # Parse PAGE_COUNT from the first line, then strip it from raw_text
    lines = full_text.splitlines()
    page_count = 1
    if lines and lines[0].startswith("PAGE_COUNT:"):
        try:
            page_count = int(lines[0].split(":", 1)[1].strip())
        except ValueError:
            pass
        lines = lines[1:]

    pdf_content: PDFContent = {
        "raw_text": "\n".join(lines).strip(),
        "tables": [],
        "page_count": page_count,
        "metadata": {},
    }

    return {"pdf_content": pdf_content}
