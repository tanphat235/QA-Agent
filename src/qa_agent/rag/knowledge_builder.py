"""
One-time offline script: build the RAG knowledge cache from the QA knowledge docx
and the approved sample drawings.

Usage:
    python -m qa_agent.rag.knowledge_builder          # build if cache absent
    python -m qa_agent.rag.knowledge_builder --force  # always rebuild

Writes: src/qa_agent/rag/data/knowledge_cache.json
"""
from __future__ import annotations

import base64
import json
import logging
import sys
from pathlib import Path

import docx as python_docx
from anthropic import Anthropic

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
_PROJECT_ROOT  = Path(__file__).parent.parent.parent.parent   # …/qa_agent/
_KNOWLEDGE_DIR = _PROJECT_ROOT / "QA AI Drawing" / "QA Knowledge"
_SAMPLE_DIR    = _KNOWLEDGE_DIR / "Sample drawings"
_DOCX_PATH     = _KNOWLEDGE_DIR / "structural_qa_rag_knowledge_pack.docx"
_CACHE_PATH    = Path(__file__).parent / "data" / "knowledge_cache.json"

_DOMAINS = ("spell", "bend", "rebar")

# Keywords that mark the start of each domain section in the docx
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "spell": ["spell check node"],
    "bend":  ["bend check node"],
    "rebar": ["rebar check node"],
}

# ── Per-domain extraction prompts for sample drawings ─────────────────────────
_EXTRACT_PROMPTS: dict[str, str] = {
    "spell": """\
This is a CORRECT, APPROVED precast wall structural drawing used as a QA reference.
Analyze it for the SPELL CHECK domain and extract concisely:
1. Section cut designations (e.g. 1-1, 2-2, 3-3) called out in the Ansicht or Bewehrung,
   and whether the corresponding Schnitt X-X views are all present on the sheet.
2. Component/element name on the Wandansicht vs the drawing name in the title block — do they match?
3. Scale labels (M 1:XX) on each view vs the title block value.
4. Whether Einbauteilliste and Montageteilliste are both present.
5. How built-in parts are labeled in the views — quote 2–3 actual label examples.
6. Whether a 3D view is present; briefly describe how it matches the Ansicht.
7. Any notable correct German spelling conventions or abbreviations used in this drawing.
Be specific and include actual values where visible.\
""",
    "bend": """\
This is a CORRECT, APPROVED precast wall structural drawing used as a QA reference.
Analyze it for the BEND CHECK domain and extract concisely:
1. Pos numbers listed in the Stabliste (list them) — note which ones have schemas in the Bewehrung.
2. Whether a Mattenstahlliste is present; if so, list mesh Pos numbers and compute the
   mesh-to-total mass ratio: (total_mesh_mass / (total_rebar_mass + total_mesh_mass)) × 100.
3. Verify mass arithmetic for 2–3 rows: n × length × unit_mass vs shown total.
4. Bar diameters seen in schemas and any mandrel diameters explicitly labeled.
5. 2–3 schema lengths (L shown in schema) vs corresponding Einzel Länge in the Stabliste.
Be specific and include actual numbers.\
""",
    "rebar": """\
This is a CORRECT, APPROVED precast wall structural drawing used as a QA reference.
Analyze it for the REBAR CHECK domain and extract concisely:
1. All spacer/clamp labels visible — do they end with "-M.E."? Quote the actual labels.
2. Wall thickness (wall_width) and concrete cover (Cv) values from the detail view.
3. Vertical pin labels and widths; verify against formula: wall_width – 2×Cv.
4. Horizontal pin labels and widths; verify against: wall_width – 2×Cv – 2×Ø_layer1
   (Ø_layer1 = outermost rebar layer diameter from the side section label).
5. Spacer/clamp widths; verify against: wall_width – 2×Cv + 2×Ø_spacer.
Be specific and include actual numbers and the formulas applied.\
""",
}


# ── Docx parser ───────────────────────────────────────────────────────────────

def _parse_docx(path: Path) -> dict[str, str]:
    """Extract and group docx paragraphs by node domain based on section headers."""
    doc = python_docx.Document(str(path))
    sections: dict[str, list[str]] = {d: [] for d in _DOMAINS}
    current: str | None = None

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        lower = text.lower()
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                current = domain
                break
        if current:
            sections[current].append(text)

    return {d: "\n".join(lines) for d, lines in sections.items()}


# ── PDF analyzer ──────────────────────────────────────────────────────────────

def _analyze_pdf(client: Anthropic, pdf_path: Path, domain: str) -> str:
    """Use Claude to extract domain-specific reference knowledge from one sample drawing."""
    with open(pdf_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()

    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": data},
                },
                {"type": "text", "text": _EXTRACT_PROMPTS[domain]},
            ],
        }],
    )
    return resp.content[0].text.strip()  # type: ignore[union-attr]


# ── Builder entry point ───────────────────────────────────────────────────────

def build(force: bool = False) -> None:
    if _CACHE_PATH.exists() and not force:
        print(f"Cache already exists at {_CACHE_PATH}\nUse --force to rebuild.")
        return

    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("Parsing QA knowledge docx …")
    docx_knowledge = _parse_docx(_DOCX_PATH)
    for d, text in docx_knowledge.items():
        print(f"  [{d}] {len(text)} chars")

    client = Anthropic()
    sample_pdfs = sorted(_SAMPLE_DIR.glob("*.pdf"))
    print(f"\nFound {len(sample_pdfs)} sample drawing(s) in {_SAMPLE_DIR}")

    samples: list[dict] = []
    for pdf_path in sample_pdfs:
        print(f"\n  [{pdf_path.name}]")
        entry: dict = {"filename": pdf_path.name, "domains": {}}
        for domain in _DOMAINS:
            print(f"    → {domain} …", end="", flush=True)
            entry["domains"][domain] = _analyze_pdf(client, pdf_path, domain)
            print(" done")
        samples.append(entry)

    cache = {
        "docx_knowledge": docx_knowledge,
        "sample_references": samples,
    }

    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"\nCache written → {_CACHE_PATH}")
    print(f"  {len(samples)} sample drawing(s), {len(_DOMAINS)} domains each.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build(force="--force" in sys.argv)
