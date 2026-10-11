"""BGB 2008 from the born-digital yearly PDF.

The file has no Persée outline. PyMuPDF keeps the InDesign text layer; pypdf
inserts spaces inside words, so this module does not use it. Output is the
same plain-text JATS shape as ``bhb.ingest.persee_pdf``, and the shared JATS
reader turns it into records.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from lxml import etree
from rapidfuzz import fuzz, process

from bhb.sections import heading_level
from bhb.textutil import fold

# 2008 print numbers are five digits (the series is in the 60,000s). A four-digit
# line is a year or a page count, not an entry. Particles such as "de", "van" and
# "vanden" are printed in lowercase; some titles start with a year ("750e", "100 jaar").
_PARTICLE = (
    r"(?:van der|van den|van de|vanden|de la|de|van|der|den|ten|ter|du|des|von|af|d'|l')"
)
_ENTRY = re.compile(
    rf"^(\d{{5}})(bis|ter|quater)?\s+((?:{_PARTICLE}\s+)?(?:[A-ZÀ-Ý«“\"\[]|\d).*)$"
)
_HEADER = re.compile(
    r"^(?:Bibliographie de l'Histoire de Belgique|Bibliografie van de Geschiedenis van België)\s*$",
    re.IGNORECASE,
)
_PAGE_MARK = re.compile(r"^\d+\*$")
_FOOTNOTE = re.compile(r"^\(\d{1,2}\)\s+\S")
_HEADING = re.compile(
    r"^(?:[IVX]{1,4}\.|[A-Z]\.|\d{1,2}[.)]|[a-z][.)])\s+\S"
)


@dataclass
class PdfLine:
    page: int
    text: str


@dataclass
class Block:
    kind: str  # "entry" or "heading"
    text: str
    page: int
    number: str = ""
    level: int = 0
    lines: list[str] = field(default_factory=list)


def convert_pdf(pdf: Path, out: Path, year: str = "2008") -> dict:
    lines = extract_lines(pdf)
    blocks = segment(lines, known_heading_labels())
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_jats(blocks, out, year, pdf.name)
    entries = [block for block in blocks if block.kind == "entry"]
    report = {
        "year": year,
        "entries": len(entries),
        "first": entries[0].number if entries else None,
        "last": entries[-1].number if entries else None,
        "headings": len([block for block in blocks if block.kind == "heading"]),
        "source": pdf.name,
    }
    out.with_suffix(".report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def extract_lines(pdf: Path) -> list[PdfLine]:
    import pymupdf

    document = pymupdf.open(pdf)
    lines: list[PdfLine] = []
    for index, page in enumerate(document):
        for raw in page.get_text().splitlines():
            text = raw.strip()
            if not text or _HEADER.match(text) or _PAGE_MARK.match(text):
                continue
            lines.append(PdfLine(index + 1, text))
    return lines


def segment(lines: list[PdfLine], labels: list[str] | None = None) -> list[Block]:
    known = known_heading_labels() if labels is None else labels
    start = _bibliography_start(lines)
    blocks: list[Block] = []
    skipping_note = False
    for line in lines[start:]:
        if _ENTRY.match(line.text):
            skipping_note = False
            match = _ENTRY.match(line.text)
            assert match is not None
            number = match.group(1) + (match.group(2) or "").lower()
            blocks.append(Block("entry", match.group(3), line.page, number, lines=[match.group(3)]))
            continue
        if _FOOTNOTE.match(line.text) and blocks and blocks[-1].kind == "entry":
            skipping_note = True
            continue
        if skipping_note and not _is_heading(line.text, known):
            continue
        skipping_note = False
        if _is_heading(line.text, known):
            blocks.append(Block("heading", line.text, line.page, lines=[line.text]))
            continue
        if not blocks:
            continue
        blocks[-1].lines.append(line.text)
        blocks[-1].text = _join(blocks[-1].lines)
    _assign_levels(blocks)
    return blocks


def _bibliography_start(lines: list[PdfLine]) -> int:
    """First numbered entry, then back up over the section headings that introduce it."""
    first = next((index for index, line in enumerate(lines) if _ENTRY.match(line.text)), 0)
    start = first
    index = first - 1
    while index >= 0:
        text = lines[index].text
        if _ENTRY.match(text) or len(text) >= 160:
            break
        start = index
        index -= 1
    return start


def _is_heading(text: str, labels: list[str]) -> bool:
    """2008 uses the modern scheme: the number must fit, and the text must match a known label."""
    if not _HEADING.match(text):
        return False
    if _ENTRY.match(text) or re.search(r"\bpp?\.\s*\d", text):
        return False
    if len(text) >= 220 or not labels or re.search(r"\.{4,}", text):
        return False
    label = fold(re.sub(r"^(?:[IVX]{1,4}\.|[A-Z]\.|\d{1,2}[.)]|[a-z][.)])\s*", "", text, count=1))
    if len(label) < 4:
        return False
    # token_set_ratio is 100 when the line merely contains a short label.
    # Prefer the longest label that still fits the line, and reject a line
    # that is more than three tokens longer than that label.
    matches = process.extract(label, labels, scorer=fuzz.token_set_ratio, score_cutoff=80, limit=15)
    matches.sort(key=lambda item: len(item[0].split()), reverse=True)
    candidate = len(label.split())
    return any(candidate <= len(matched.split()) + 3 for matched, _score, _index in matches)


@lru_cache(maxsize=1)
def known_heading_labels() -> list[str]:
    """Folded labels from the 2005–2007 print headings and, when present, the scheme file."""
    from bhb.paths import raw_available, raw_root, repo_root

    root = raw_root() if raw_available() else None
    code_root = repo_root()
    found: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        folded = fold(text)
        if len(folded) < 8 or folded in seen or re.fullmatch(r"\d{4}", folded):
            return
        seen.add(folded)
        found.append(folded)

    for year in ("2005", "2006", "2007"):
        if root is None:
            break
        matches = list((root / "2023-12-29").rglob(f"BGB_{year}.xml"))
        if not matches:
            continue
        raw = matches[0].read_text(encoding="utf-8", errors="replace")
        for title in re.findall(r"<title>(.*?)</title>", raw, flags=re.S):
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", title))).strip()
            body = re.sub(
                r"^(?:[IVX]{1,4}\.|[A-Z]\.|\d{1,2}[.)]|[a-z][.)])\s*",
                "",
                text,
                count=1,
            )
            add(body)
            for piece in re.split(r"[—–]|-", body):
                add(piece)
    scheme = code_root / "build" / "scheme.json"
    if scheme.is_file():
        for row in json.loads(scheme.read_text(encoding="utf-8")):
            for key in ("label_fr", "label_nl"):
                label = row.get(key) or ""
                for piece in label.split("/"):
                    add(piece)
    return found


def _join(lines: list[str]) -> str:
    out = ""
    for piece in lines:
        piece = piece.strip()
        if not piece:
            continue
        if out.endswith("-") and piece[:1].islower():
            out = out[:-1] + piece
        elif not out:
            out = piece
        else:
            out += " " + piece
    return re.sub(r"\s{2,}", " ", out).strip()


def _assign_levels(blocks: list[Block]) -> None:
    stack: list[tuple[int, str]] = []
    for block in blocks:
        if block.kind != "heading":
            continue
        level = heading_level(block.text, stack)
        stack = [item for item in stack if item[0] < level]
        stack.append((level, block.text))
        block.level = level


def _write_jats(blocks: list[Block], out: Path, year: str, source_name: str) -> None:
    article = etree.Element("article")
    article.set("article-type", "bibliography")
    front = etree.SubElement(article, "front")
    meta = etree.SubElement(front, "article-meta")
    etree.SubElement(meta, "article-id", {"pub-id-type": "bgb-year"}).text = year
    back = etree.SubElement(article, "back")
    parents = {0: back}
    current = back
    for block in blocks:
        if block.kind == "heading":
            parent = parents[max(level for level in parents if level < block.level)]
            ref_list = etree.SubElement(parent, "ref-list")
            etree.SubElement(ref_list, "title").text = block.text
            parents = {level: node for level, node in parents.items() if level < block.level}
            parents[block.level] = ref_list
            current = ref_list
            continue
        ref = etree.SubElement(current, "ref", {"id": f"ref{block.number}"})
        ref.set("specific-use", f"pdf-page:{block.page}")
        etree.SubElement(ref, "label").text = block.number
        etree.SubElement(ref, "mixed-citation", {"publication-type": "unknown"}).text = block.text
    etree.ElementTree(article).write(str(out), xml_declaration=True, encoding="utf-8", pretty_print=True)
    del source_name
