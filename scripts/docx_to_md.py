"""
Convert structural_qa_rag_knowledge_pack.docx -> per-check Markdown files.

Check ranges use NON-EMPTY paragraph indices (matching the dump analysis).
Images are collected from ALL paragraphs (incl. empty image-only paragraphs)
in the same range by mapping nonempty-idx <-> all-para-idx.

Output:
  QA AI Drawing/QA Knowledge/
    common/terminology.md
    spell/spelling.md  ...
    bend/bar_length/bar_length.md + img_001.png ...
    rebar/pin_width_vertical/pin_width_vertical.md + img_001.png ...
"""

from __future__ import annotations
import re
from pathlib import Path
import docx as docx_mod

REPO_ROOT  = Path(__file__).resolve().parent.parent
DOCX_PATH  = REPO_ROOT / "QA AI Drawing" / "QA Knowledge" / "structural_qa_rag_knowledge_pack.docx"
OUTPUT_DIR = REPO_ROOT / "QA AI Drawing" / "QA Knowledge"

# ── Ranges use NON-EMPTY paragraph indices from dump analysis ──────────────
STRUCTURE: dict[str, dict[str, tuple[int, int]]] = {
    "common": {
        "terminology": (3, 16),
    },
    "spell": {
        "spelling":         (19, 19),
        "section_name":     (20, 20),
        "component_name":   (21, 21),
        "section_scale":    (22, 22),
        "grid_lines":       (23, 23),
        "parts_lists":      (24, 24),
        "parts_quantities": (25, 25),
        "3d_view":          (27, 27),
        "drawing_title":    (28, 28),
        "_output_format":   (29, 35),
    },
    "bend": {
        "pos_count":        (38, 38),
        "mesh_pos":         (39, 39),
        "mesh_ratio":       (40, 41),
        "mass_arithmetic":  (42, 43),
        "pos_coverage":     (44, 45),
        "bending_angle":    (46, 53),
        "bar_length":       (54, 56),
        "_output_format":   (57, 64),
    },
    "rebar": {
        "spacer_label":           (67, 67),
        "pin_width_vertical":     (68, 72),
        "pin_width_horizontal":   (73, 77),
        "spacer_width":           (78, 82),
        "_output_format":         (83, 89),
    },
}

CHECK_TITLES: dict[str, str] = {
    "spelling":           "Spelling Errors",
    "section_name":       "Section Name Completeness",
    "component_name":     "Component Name vs Title Block",
    "section_scale":      "Scale Consistency",
    "grid_lines":         "Formwork Grid Lines Consistency",
    "parts_lists":        "Parts Lists Present",
    "parts_quantities":   "Parts Label Consistency",
    "3d_view":            "3D View Present",
    "drawing_title":      "Drawing Title vs Title Block",
    "pos_count":          "Last Position Number vs Title Block",
    "pos_coverage":       "Pos Coverage in Schemas",
    "mesh_pos":           "Mesh Reinforcement Pos",
    "mesh_ratio":         "Mesh-to-Total Mass Ratio",
    "mass_arithmetic":    "Total Mass Arithmetic",
    "bending_angle":      "Bending Angle / Mandrel Diameter",
    "bar_length":         "Bar Length vs Schedule",
    "spacer_label":       "Spacer / Clamp Label Suffix",
    "pin_width_vertical": "Vertical Pin Width",
    "pin_width_horizontal": "Horizontal Pin Width",
    "spacer_width":       "Spacer / Clamp Width",
}

DOMAIN_TITLES: dict[str, str] = {
    "common": "Common",
    "spell":  "Spelling & Title Block",
    "bend":   "Bending & Schedule",
    "rebar":  "Rebar Labels & Dims",
}

R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"

EXT_MAP: dict[str, str] = {
    "image/png":  ".png",
    "image/jpeg": ".jpg",
    "image/gif":  ".gif",
    "image/webp": ".webp",
}


def build_index_map(all_paras: list) -> dict[int, int]:
    """Map nonempty_idx -> all_paras_idx."""
    mapping: dict[int, int] = {}
    ni = 0
    for ai, p in enumerate(all_paras):
        if p.text.strip():
            mapping[ni] = ai
            ni += 1
    return mapping


def collect_images(
    start_ne: int,
    end_ne: int,
    all_paras: list,
    ne_to_all: dict[int, int],
    rid_to_part: dict,
) -> list[tuple[bytes, str]]:
    """Collect images from all paragraphs (incl. empty) in the check range.

    Extends past the last non-empty paragraph to capture image-only empty
    paragraphs that appear after the text description, up to (but not
    including) the first paragraph of the next check.
    """
    start_ai = ne_to_all[start_ne]
    # Extend to include empty-image paragraphs that follow the last text para
    next_ne = end_ne + 1
    if next_ne in ne_to_all:
        extended_end = ne_to_all[next_ne] - 1
    else:
        extended_end = len(all_paras) - 1

    images: list[tuple[bytes, str]] = []
    seen: set[str] = set()
    for para in all_paras[start_ai : extended_end + 1]:
        for elem in para._element.iter():
            rid = elem.get(R_EMBED)
            if rid and rid in rid_to_part and rid not in seen:
                seen.add(rid)
                part = rid_to_part[rid]
                images.append((part.blob, part.content_type))
    return images


def para_to_md(para) -> str:
    text = para.text.strip()
    if not text:
        return ""
    full_bold = bool(para.runs) and all(r.bold for r in para.runs if r.text.strip())
    return f"**{text}**" if full_bold else text


def write_check_md(
    check_key: str,
    domain: str,
    para_range: tuple[int, int],
    of_paras: list,
    all_paras: list,
    ne_to_all: dict[int, int],
    nonempty_paras: list,
    rid_to_part: dict,
) -> None:
    title = CHECK_TITLES.get(check_key, check_key)
    domain_title = DOMAIN_TITLES.get(domain, domain)

    start_ne, end_ne = para_range
    text_paras = nonempty_paras[start_ne : end_ne + 1]
    images = collect_images(start_ne, end_ne, all_paras, ne_to_all, rid_to_part)

    check_dir = OUTPUT_DIR / domain / check_key
    check_dir.mkdir(parents=True, exist_ok=True)
    md_path = check_dir / f"{check_key}.md"

    image_refs: list[str] = []
    for idx, (blob, content_type) in enumerate(images, start=1):
        ext = EXT_MAP.get(content_type, ".png")
        fname = f"img_{idx:03d}{ext}"
        (md_path.parent / fname).write_bytes(blob)
        image_refs.append(f"![{title} example {idx}](./{fname})")

    lines: list[str] = [
        f"# {title}",
        f"> **Domain:** {domain_title} | **Check key:** `{check_key}`",
        "",
        "## Description",
        "",
    ]
    for para in text_paras:
        md_line = para_to_md(para)
        if md_line:
            lines.append(md_line)
            lines.append("")

    if image_refs:
        lines.append("## Reference Images")
        lines.append("")
        lines.extend(ref + "\n" for ref in image_refs)

    if of_paras:
        lines.append("## Output Format")
        lines.append("")
        for para in of_paras:
            md_line = para_to_md(para)
            if md_line:
                lines.append(md_line)
                lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    img_note = f" ({len(images)} image(s))" if images else ""
    print(f"  + {md_path.relative_to(OUTPUT_DIR)}{img_note}")


def write_terminology_md(
    nonempty_paras: list,
    all_paras: list,
    ne_to_all: dict[int, int],
    rid_to_part: dict,
) -> None:
    start_ne, end_ne = STRUCTURE["common"]["terminology"]
    text_paras = nonempty_paras[start_ne : end_ne + 1]
    images = collect_images(start_ne, end_ne, all_paras, ne_to_all, rid_to_part)

    out_dir = OUTPUT_DIR / "common"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "terminology.md"

    lines: list[str] = [
        "# Common Terminology",
        "> Shared German/English glossary used across all QA checks.",
        "",
        "## Glossary",
        "",
    ]
    for para in text_paras:
        text = para.text.strip()
        if not text:
            continue
        match = re.match(r"^([^:=]+)([=:])(.+)$", text)
        if match:
            term, sep, definition = match.groups()
            lines.append(f"**{term.strip()}**{sep}{definition}")
        else:
            lines.append(text)
        lines.append("")

    if images:
        lines.append("## Reference Images")
        lines.append("")
        for idx, (blob, content_type) in enumerate(images, start=1):
            ext = EXT_MAP.get(content_type, ".png")
            fname = f"img_{idx:03d}{ext}"
            (out_dir / fname).write_bytes(blob)
            lines.append(f"![Terminology example {idx}](./{fname})")
            lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    img_note = f" ({len(images)} image(s))" if images else ""
    print(f"  + common/terminology.md{img_note}")


def main() -> None:
    print(f"Reading: {DOCX_PATH.name}")
    doc = docx_mod.Document(str(DOCX_PATH))

    rid_to_part: dict = {
        rel.rId: rel.target_part
        for rel in doc.part.rels.values()
        if "image" in rel.reltype
    }

    all_paras    = list(doc.paragraphs)
    nonempty_paras = [p for p in all_paras if p.text.strip()]
    ne_to_all    = build_index_map(all_paras)

    print(f"All paragraphs: {len(all_paras)}, non-empty: {len(nonempty_paras)}, images: {len(rid_to_part)}")
    print()

    print("[common]")
    write_terminology_md(nonempty_paras, all_paras, ne_to_all, rid_to_part)
    print()

    for domain, checks in STRUCTURE.items():
        if domain == "common":
            continue
        print(f"[{domain}]")

        of_range = checks.get("_output_format")
        of_paras = (
            nonempty_paras[of_range[0] : of_range[1] + 1] if of_range else []
        )

        for check_key, para_range in checks.items():
            if check_key.startswith("_"):
                continue
            write_check_md(
                check_key=check_key,
                domain=domain,
                para_range=para_range,
                of_paras=of_paras,
                all_paras=all_paras,
                ne_to_all=ne_to_all,
                nonempty_paras=nonempty_paras,
                rid_to_part=rid_to_part,
            )
        print()

    # Remove orphaned flat .md files at the domain level that now live in subfolders
    removed = []
    for domain, checks in STRUCTURE.items():
        if domain == "common":
            continue
        for check_key in checks:
            if check_key.startswith("_"):
                continue
            flat = OUTPUT_DIR / domain / f"{check_key}.md"
            if flat.exists():
                flat.unlink()
                removed.append(flat.relative_to(OUTPUT_DIR))
    if removed:
        print("Removed orphaned flat files:")
        for p in removed:
            print(f"  - {p}")
        print()

    print("Done!")


if __name__ == "__main__":
    main()
