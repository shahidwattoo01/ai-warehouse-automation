"""Document ingestion: PDF text extraction -> heading-aware chunking -> (embeddings ->
warehouse_docs).

The pipeline starts from the PDFs in data/documents/pdf/, as it would with a real site's
manuals. Two chunking strategies are compared in notebooks/12_rag.ipynb:

* "section": one chunk per numbered section (WM-2.1, SOP-04 ...). Sections are the units the
  documents are written in, so a chunk never mixes two topics and can be cited exactly.
* "fixed": windows of N words with overlap, ignoring the structure (the common default).

Every chunk keeps the section ids it covers, so retrieval can be scored against the
evaluation questions (data/processed/rag/questions.jsonl), which cite sections.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = ROOT / "data" / "documents" / "pdf"
DOC_ORDER = [
    "warehouse_manual",
    "robot_manual",
    "safety_rules",
    "maintenance_guides",
    "sops",
    "inventory_policies",
    "shipping_policies",
]
DOC_TYPE = {  # warehouse_docs.doc_type: lets a query search one kind of document
    "warehouse_manual": "manual",
    "robot_manual": "manual",
    "safety_rules": "safety",
    "maintenance_guides": "maintenance",
    "sops": "sop",
    "inventory_policies": "policy",
    "shipping_policies": "policy",
}
SECTION_ID = re.compile(r"^([A-Z]{2,4}-\d+(?:\.\d+)?)\b\s*(.*)$")
BULLET = re.compile(r"^[\x7f\uf0b7\u2022\u25aa\u25cf]\s*")  # bullet glyphs pypdf extracts


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section_id: str  # first section in the chunk (the citation)
    heading: str
    text: str
    sections: list[str] = field(default_factory=list)  # every section the chunk covers

    @property
    def doc_type(self) -> str:
        return DOC_TYPE.get(self.doc_id, "other")

    def for_embedding(self) -> str:
        """The text that is embedded and searched: document and heading first (a "contextual
        chunk header"), so "SOP-04" alone still knows it is about an overheating robot."""
        return f"{self.title} · {self.heading}\n{self.text}"

    def to_dict(self) -> dict:
        return {**asdict(self), "doc_type": self.doc_type}


def pdf_lines(path: Path) -> tuple[str, list[str]]:
    """Title and the cleaned text lines of a PDF (bullets become "- ")."""
    from pypdf import PdfReader

    lines: list[str] = []
    for page in PdfReader(path).pages:
        for line in (page.extract_text() or "").splitlines():
            line = BULLET.sub("- ", line.strip())
            if line:
                lines.append(line)
    title = lines[0] if lines else path.stem
    body = lines[2:] if len(lines) > 2 and lines[1].startswith("Version") else lines[1:]
    return title, body


def _sections(lines: list[str]) -> list[tuple[str, str, list[str]]]:
    """(section id, heading, lines) for every block that starts with a section id."""
    out: list[tuple[str, str, list[str]]] = []
    heading = ""
    prefix = None  # every id of a document shares its prefix (WM-, SHP-); codes such as door
    for line in lines:  # SHIP-01 at the start of a table row are not sections
        m = SECTION_ID.match(line)
        if m and prefix and m.group(1).split("-")[0] != prefix:
            m = None
        if m:
            prefix = prefix or m.group(1).split("-")[0]
            sid, rest = m.groups()
            if "." not in sid and rest:  # "WM-2 Building layout" / "SOP-04 Overheating robot"
                heading = rest
            out.append((sid, heading, [line]))
        elif out:
            out[-1][2].append(line)
    return out


def section_chunks(doc_id: str, path: Path) -> list[Chunk]:
    title, lines = pdf_lines(path)
    chunks = []
    for sid, heading, block in _sections(lines):
        text = "\n".join(block)
        if len(block) == 1 and len(text.split()) <= 6:
            continue  # a heading followed by numbered paragraphs carries no text of its own
        chunks.append(Chunk(f"{doc_id}#{sid}", doc_id, title, sid, heading, text, [sid]))
    return chunks


def fixed_chunks(doc_id: str, path: Path, size: int = 120, overlap: int = 30) -> list[Chunk]:
    """Windows of `size` words, each starting `size - overlap` words after the previous one."""
    title, lines = pdf_lines(path)
    words: list[str] = []
    starts: list[tuple[int, str, str]] = []  # (word index, section id, heading)
    for sid, heading, block in _sections(lines):
        starts.append((len(words), sid, heading))
        for line in block:
            words.extend(line.split())
    ends = [s[0] for s in starts[1:]] + [len(words)]
    chunks = []
    step = size - overlap
    for i, a in enumerate(range(0, max(len(words) - overlap, 1), step)):
        b = min(a + size, len(words))
        covered = [s for (st, s, _), en in zip(starts, ends, strict=True) if st < b and en > a]
        first = next(((s, h) for st, s, h in reversed(starts) if st <= a), (covered[0], ""))
        chunks.append(
            Chunk(
                f"{doc_id}#w{i}",
                doc_id,
                title,
                first[0],
                first[1],
                " ".join(words[a:b]),
                covered,
            )
        )
    return chunks


def load_chunks(strategy: str = "section", pdf_dir: Path = PDF_DIR, **options) -> list[Chunk]:
    """All chunks of all documents, in document order."""
    make = section_chunks if strategy == "section" else fixed_chunks
    out: list[Chunk] = []
    for doc_id in DOC_ORDER:
        path = pdf_dir / f"{doc_id}.pdf"
        if path.exists():
            out.extend(make(doc_id, path, **options) if options else make(doc_id, path))
    return out
