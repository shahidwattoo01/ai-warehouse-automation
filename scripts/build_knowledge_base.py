"""Build the RAG knowledge base files from the Markdown sources in data/documents/.

    python scripts/build_knowledge_base.py

The Markdown files are the source of truth (easy to review and keep consistent with
configs/simulation.yaml). This script:

1. splits every document into its numbered sections (WM-2.1, SOP-05, ...) and writes
   data/processed/rag/sections.jsonl - the ground-truth units that retrieval should find;
2. checks that every evaluation question cites sections that exist, and writes
   data/processed/rag/questions.jsonl;
3. renders each document to PDF in data/documents/pdf/, because the RAG pipeline is meant to
   start from PDFs (text extraction -> chunking -> embeddings -> vector database).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "data" / "documents"
OUT = ROOT / "data" / "processed" / "rag"
PDF_DIR = DOCS / "pdf"
DOC_ORDER = [
    "warehouse_manual",
    "robot_manual",
    "safety_rules",
    "maintenance_guides",
    "sops",
    "inventory_policies",
    "shipping_policies",
]
SECTION_ID = re.compile(r"^(?:#+\s+)?([A-Z]{2,4}-\d+(?:\.\d+)?)\b\s*(.*)$")


def read_doc(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    return yaml.safe_load(front), body.strip()


def sections(doc_id: str, body: str) -> list[dict]:
    """Every block that starts with a section id, up to the next one."""
    out: list[dict] = []
    current: dict | None = None
    heading = ""
    for block in re.split(r"\n\s*\n", body):
        first = block.strip().splitlines()[0] if block.strip() else ""
        m = SECTION_ID.match(first)
        if first.startswith("## ") and m:
            heading = m.group(2)
        if m:
            current = {
                "doc_id": doc_id,
                "section_id": m.group(1),
                "heading": heading,
                "text": block.strip(),
            }
            out.append(current)
        elif current is not None:
            current["text"] += "\n\n" + block.strip()
    for s in out:
        s["text"] = re.sub(r"^#+\s+", "", s["text"])
    # A heading directly followed by numbered paragraphs carries no text of its own.
    return [s for s in out if "\n" in s["text"] or len(s["text"].split()) > 6]


def render_pdf(meta: dict, body: str, path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()

    def inline(text: str) -> str:
        text = escape(text)
        text = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', text)
        return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)

    story = [
        Paragraph(inline(meta["title"]), styles["Title"]),
        Paragraph(
            inline(
                f"Version {meta['version']} - effective {meta['effective']}"
                f" - owner: {meta['owner']}"
            ),
            styles["Italic"],
        ),
        Spacer(1, 6 * mm),
    ]
    for block in re.split(r"\n\s*\n", body):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        if lines[0].startswith("# "):
            continue  # the title is already on the page
        if lines[0].startswith("## "):
            story.append(Paragraph(inline(lines[0][3:]), styles["Heading2"]))
            lines = lines[1:]
            if not lines:
                continue
        if all(ln.lstrip().startswith("|") for ln in lines):
            rows = [
                [
                    Paragraph(inline(c.strip()), styles["BodyText"])
                    for c in ln.strip().strip("|").split("|")
                ]
                for ln in lines
                if not re.match(r"^\|[\s\-|]+\|$", ln.strip())
            ]
            table = Table(rows, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7EEFB")),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C2CF")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story += [Spacer(1, 2 * mm), table, Spacer(1, 3 * mm)]
            continue
        para: list[str] = []
        for ln in lines:
            item = re.match(r"^\s*(?:-|\d+\.)\s+(.*)$", ln)
            if item:
                if para:
                    story.append(Paragraph(inline(" ".join(para)), styles["BodyText"]))
                    para = []
                story.append(Paragraph(inline(item.group(1)), styles["BodyText"], bulletText="•"))
            elif para or not ln.startswith(" "):
                para.append(ln.strip())
            else:
                para.append(ln.strip())
        if para:
            story.append(Paragraph(inline(" ".join(para)), styles["BodyText"]))
    SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title=meta["title"],
        author=meta["owner"],
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    ).build(story)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    all_sections: list[dict] = []
    for doc_id in DOC_ORDER:
        meta, body = read_doc(DOCS / f"{doc_id}.md")
        assert meta["doc_id"] == doc_id, doc_id
        secs = sections(doc_id, body)
        for s in secs:
            s["title"] = meta["title"]
        all_sections += secs
        render_pdf(meta, body, PDF_DIR / f"{doc_id}.pdf")
        print(f"  {doc_id:20s} {len(secs):3d} sections -> pdf/{doc_id}.pdf")

    known = {f"{s['doc_id']}#{s['section_id']}" for s in all_sections}
    dupes = len(known) != len(all_sections)
    questions = yaml.safe_load((DOCS / "eval" / "rag_questions.yaml").read_text(encoding="utf-8"))
    missing = [(q["id"], src) for q in questions for src in q["sources"] if src not in known]
    bad_type = [q["id"] for q in questions if (q["type"] == "unanswerable") != (not q["sources"])]
    if missing or dupes or bad_type:
        print("Problems:", {"missing_sources": missing, "duplicate_ids": dupes, "type": bad_type})
        return 1

    with (OUT / "sections.jsonl").open("w", encoding="utf-8") as f:
        for s in all_sections:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with (OUT / "questions.jsonl").open("w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    types = {
        t: sum(q["type"] == t for q in questions) for t in sorted({q["type"] for q in questions})
    }
    print(f"{len(all_sections)} sections, {len(questions)} questions {types} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
