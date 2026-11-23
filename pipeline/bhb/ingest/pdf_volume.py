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

# 2008 print numbers are five digits (the series is in the 60,000s); from 2013 they pass 100,000 and have six. A
# four-digit line is a year or a page count, not an entry. Particles such as "de", "van" and
# "vanden" are printed in lowercase; some titles start with a year ("750e", "100 jaar").
_PARTICLE = (
    r"(?:van der|van den|van de|vanden|de la|de|van|der|den|ten|ter|du|des|von|af|d'|l')"
)
_ENTRY = re.compile(
    rf"^(\d{{5,6}})(bis|ter|quater)?\s+((?:{_PARTICLE}\s+)?(?:[A-ZÀ-Ý«“\"\[]|\d).*)$"
)
_HEADER = re.compile(
    r"^(?:Bibliographie de l'Histoire de Belgique|Bibliografie van de Geschiedenis van België)\s*$",
    re.IGNORECASE,
)
_PAGE_MARK = re.compile(r"^\d+\*$")
# A line of the index of names or places that follows the last entry: "Abbeloos (Jan-Frederik): 62743, 62774".
_INDEX_LINE = re.compile(r"^[^:]{2,80}:\s*\d{5}(?:,\s*\d{5})*,?$")
_FOOTNOTE = re.compile(r"^\(\d{1,2}\)\s+\S")
# Below the lettered headings, 2008 prints "(1) …" and "(a) …", as the 2005–2007 volumes do.
_NUMBER = r"(?:[IVX]{1,4}\.|[A-Z]\.|\d{1,2}[.)]|[a-z][.)]|\(\d{1,2}\)|\([a-z]\))"
_HEADING = re.compile(rf"^{_NUMBER}\s+\S")


@dataclass
class PdfLine:
    page: int
    text: str
    x: float = 0.0  # left edge, relative to the page's text margin (unnumbered volumes only)


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
    numbered = sum(block.kind == "entry" for block in blocks) >= 50
    if not numbered:
        # From 2016 the volumes print no numbers: an entry starts at the text margin, its other lines are indented.
        blocks = segment_unnumbered(extract_positioned_lines(pdf), known_heading_labels())
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_jats(blocks, out, year, pdf.name, numbered=numbered)
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


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Ligature glyphs (the volumes of 2010 and 2011 have about 900 each: "Beauﬁls", "scientiﬁque"): their letters, so that
# a search for "Beaufils" finds the entry.
_LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"})


def _clean(text: str) -> str:
    """A line of the PDF's text layer: control characters out, ligatures as letters."""
    return _CONTROL.sub("", text).translate(_LIGATURES).strip()


def extract_lines(pdf: Path) -> list[PdfLine]:
    import pymupdf

    document = pymupdf.open(pdf)
    lines: list[PdfLine] = []
    for index, page in enumerate(document):
        for raw in page.get_text().splitlines():
            # Some yearly volumes (2010) carry control characters in their text layer; XML cannot hold them.
            text = _clean(raw)
            if not text or _HEADER.match(text) or _PAGE_MARK.match(text):
                continue
            lines.append(PdfLine(index + 1, text))
    return lines


def segment(lines: list[PdfLine], labels: list[str] | None = None) -> list[Block]:
    known = known_heading_labels() if labels is None else labels
    start = _bibliography_start(lines)
    blocks: list[Block] = []
    skipping_note = False
    body = lines[start:]
    for index, line in enumerate(body):
        if all(_INDEX_LINE.match(item.text) for item in body[index : index + 3]):
            break
        if _ENTRY.match(line.text):
            skipping_note = False
            match = _ENTRY.match(line.text)
            assert match is not None
            number = match.group(1) + (match.group(2) or "").lower()
            blocks.append(Block("entry", match.group(3), line.page, number, lines=[match.group(3)]))
            continue
        # A heading wraps after the dash between its French and Dutch halves.
        if blocks and blocks[-1].kind == "heading" and blocks[-1].text.endswith("-"):
            blocks[-1].lines.append(line.text)
            blocks[-1].text = _join(blocks[-1].lines)
            continue
        # A "(2) …" sub-heading looks like a footnote, so the heading test comes first.
        if _is_heading(line.text, known) or (blocks and blocks[-1].kind == "heading" and _is_bare_heading(line.text, known)):
            skipping_note = False
            blocks.append(Block("heading", line.text, line.page, lines=[line.text]))
            continue
        if _FOOTNOTE.match(line.text) and blocks and blocks[-1].kind == "entry":
            skipping_note = True
            continue
        if skipping_note:
            continue
        if not blocks:
            continue
        blocks[-1].lines.append(line.text)
        blocks[-1].text = _join(blocks[-1].lines)
    _assign_levels(blocks)
    return blocks


# An entry of an unnumbered volume opens with its author ("Vanden Daelen (Veerle), …", "de Waha (Michel).") or "S.n.".
_AUTHOR_START = re.compile(rf"^(?:(?:{_PARTICLE})\s+|[dl][’'])?[A-ZÀ-Ý][^()]{{0,60}}\([^)]{{1,40}}\)|^S\.\s?n\.")
_ENDED = re.compile(r"[.\])»”]\s*$")
# The table of contents after the last entry: a line with its title alone ("INHOUDSTAFEL", "TABLE DES MATIÈRES …"),
# not a note in an entry ("[Inhoud : Topstukkendecreet, …]").
_CONTENTS = re.compile(r"^(?:Table des matières|Inhoudstafel|Inhoudsopgave)[\s.\d]*$", re.IGNORECASE)


def extract_positioned_lines(pdf: Path) -> list[PdfLine]:
    """Lines with their left edge relative to the page's text margin (the leftmost of its long lines)."""
    import pymupdf

    document = pymupdf.open(pdf)
    lines: list[PdfLine] = []
    for index, page in enumerate(document):
        found: list[tuple[float, str]] = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = _clean("".join(span["text"] for span in line["spans"]))
                if text and not _HEADER.match(text) and not _PAGE_MARK.match(text):
                    found.append((line["bbox"][0], text))
        long_lines = [x for x, text in found if len(text) > 40]
        margin = min(long_lines) if long_lines else 0.0
        lines.extend(PdfLine(index + 1, text, x - margin) for x, text in found)
    return lines


def segment_unnumbered(lines: list[PdfLine], labels: list[str] | None = None, margin: float = 2.0) -> list[Block]:
    """Headings and entries of a volume without entry numbers. An entry is numbered by its place, ``p1``, ``p2``…"""
    known = known_heading_labels() if labels is None else labels
    first = next((i for i, line in enumerate(lines) if line.x <= margin and _AUTHOR_START.match(line.text)), 0)
    start = first
    while start > 0 and (_is_heading(lines[start - 1].text, known) or _is_bare_heading(lines[start - 1].text, known)):
        start -= 1
    blocks: list[Block] = []
    count = 0
    for line in lines[start:]:
        if _CONTENTS.match(line.text):
            break
        if blocks and blocks[-1].kind == "heading" and blocks[-1].text.endswith("-"):
            blocks[-1].lines.append(line.text)
            blocks[-1].text = _join(blocks[-1].lines)
            continue
        if _is_heading(line.text, known) or (blocks and blocks[-1].kind == "heading" and _is_bare_heading(line.text, known)):
            blocks.append(Block("heading", line.text, line.page, lines=[line.text]))
            continue
        author = bool(_AUTHOR_START.match(line.text))
        if line.x <= margin and line.text[:1].islower() and not author and blocks and blocks[-1].kind == "heading":
            blocks[-1].lines.append(line.text)  # a heading wrapped onto a second line ("… van de politiek")
            blocks[-1].text = _join(blocks[-1].lines)
            continue
        # The other lines of an entry are indented, so a line at the margin starts one: an author ("d’Osta (Jean)"),
        # or a corporate author or title ("Redactie.", "Heemkundekring Onsenoort.") once the entry before has ended.
        starts = line.x <= margin and (author or (not line.text[:1].islower() and (
            not blocks or blocks[-1].kind == "heading" or (len(line.text) > 12 and _ENDED.search(blocks[-1].text)))))
        if starts:
            count += 1
            blocks.append(Block("entry", line.text, line.page, f"p{count}", lines=[line.text]))
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
    label = fold(re.sub(rf"^{_NUMBER}\s*", "", text, count=1))
    if len(label) < 4:
        return False
    # token_set_ratio is 100 when the line merely contains a short label.
    # Prefer the longest label that still fits the line, and reject a line
    # that is more than three tokens longer than that label.
    matches = process.extract(label, labels, scorer=fuzz.token_set_ratio, score_cutoff=80, limit=15)
    matches.sort(key=lambda item: len(item[0].split()), reverse=True)
    candidate = len(label.split())
    return any(candidate <= len(matched.split()) + 3 for matched, _score, _index in matches)


def _is_bare_heading(text: str, labels: list[str]) -> bool:
    """An unnumbered heading right under another ("Généralités - Algemeenheden"): the whole line is a known label.

    A line that goes on with a lowercase word ("van de politiek") is the heading above it, wrapped.
    """
    if not text[:1].isupper() or _ENTRY.match(text) or len(text) >= 160 or re.search(r"\.{4,}", text):
        return False
    return process.extractOne(fold(text), labels, scorer=fuzz.ratio, score_cutoff=92) is not None


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
            body = re.sub(rf"^{_NUMBER}\s*", "", text, count=1)
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


def _write_jats(blocks: list[Block], out: Path, year: str, source_name: str, numbered: bool = True) -> None:
    article = etree.Element("article")
    article.set("article-type", "bibliography")
    front = etree.SubElement(article, "front")
    meta = etree.SubElement(front, "article-meta")
    etree.SubElement(meta, "article-id", {"pub-id-type": "bgb-year"}).text = year
    if not numbered:
        # The entries carry their place ("p12") as id and no label: ``bhb.ingest.jats`` gives them that id.
        etree.SubElement(meta, "article-id", {"pub-id-type": "numbering"}).text = "none"
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
        if numbered:
            etree.SubElement(ref, "label").text = block.number
        etree.SubElement(ref, "mixed-citation", {"publication-type": "unknown"}).text = block.text
    etree.ElementTree(article).write(str(out), xml_declaration=True, encoding="utf-8", pretty_print=True)
    del source_name
