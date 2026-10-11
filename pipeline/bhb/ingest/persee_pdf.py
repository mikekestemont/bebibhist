"""Convert a BGB year from a Persée PDF (with OCR text layer) into STRAIVE-compatible JATS.

The decade PDFs on rbph-btfg.be (e.g. BGB_1960-69.pdf) are Persée exports: each
year is a separate article with a cover page ("Citer ce document"), a PDF outline
holding the section plan, and a text layer produced by OCR. This module rebuilds,
for one year, the same structure the STRAIVE files use (nested <ref-list> with
<title>, one <ref> per printed entry), so that downstream code can treat all
volumes alike. Inline citation mark-up (<source>, <year>, ...) is *not* produced:
mixed-citation holds the plain printed text and publication-type="unknown".

Segmentation relies on three signals:
  * entries are numbered consecutively, so an entry starts where the next
    expected number appears at the start of a line;
  * section headings are recognised by numbering style, confirmed by the PDF
    outline (upper levels) or by the dictionary of headings found in the
    neighbouring STRAIVE volumes (lower levels);
  * footnotes start with "(1)" and run to the bottom of the page.

Usage:
    python -m bhb.ingest.persee_pdf PDF YEAR --headings-from DIR --out FILE.xml
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from pypdf import PdfReader
from rapidfuzz import fuzz

RUNNING_HEADER = re.compile(
    r"^\s*(?:BIBLIOGRAPHIE DE L.HISTOIRE DE BELGIQUE\s+(\d+)|(\d+)\s+BIBLIOGRAFIE VAN DE GESCHIEDENIS VAN BELGI.)\s*$"
)
ENTRY_START = re.compile(r"^\s*(\d{1,5})\s?(\d{0,2})\s+(?=\S)")
FUZZY_NUMBER = re.compile(r"^\s*([\dθΘOo](?:\s?[\dθΘOo]){2,4})\s+(?=[A-ZÀ-Ý«\[(])")
OCR_DIGITS = str.maketrans("θΘOo", "8800")
BIS = re.compile(r"^\(?(bis|ter|quater)\)?\s+")
FOOTNOTE_START = re.compile(r"^\s*\((?:\d|[xl*»i])\)\s")
HEADING_ROMAN = re.compile(r"^\s*([IVX]{1,4})\.\s+\S")
HEADING_UPPER = re.compile(r"^\s*([A-HJ-KΑΒ])\.\s+\S")
HEADING_DIGIT_DOT = re.compile(r"^\s*(\d{1,2})\.\s+[A-ZÀ-ÝΑ-Ω]")
HEADING_DIGIT_PAREN = re.compile(r"^\s*(\d{1,2})\s?\)\s+[A-ZÀ-ÝΑ-Ωa-z]")
HEADING_LOWER = re.compile(r"^\s*([a-k])\s?\)\s+\S")
ENDS_ENTRY = re.compile(r"[.)\]»\d\"'·]\s*$")
CITATION_LIKE = re.compile(r"\b1[5-9]\d\d\b|\bpp?\.\s*\d|\b[IVXLC]{2,}\b,")

# Greek letters that OCR confuses with Latin ones.
LOOKALIKES = str.maketrans("ΑΒΕΗΙΚΜΝΟΡΤΧΥΖαο", "ABEHIKMNOPTXYZao")
# OCR damage to heading numbers: "IL Les églises" (II.), "£. La principauté" (E.)
HEADING_REPAIRS = [(re.compile(r"^(\s*)IL\s"), r"\1II. "), (re.compile(r"^(\s*)£\.\s"), r"\1E. ")]


@dataclass
class Line:
    pdf_page: int  # 1-based, as shown in PDF viewers
    print_page: int | None
    text: str


@dataclass
class Heading:
    style: str
    lines: list[Line]
    level: int = 0
    outline_level: int | None = None  # depth in the PDF outline, when matched there

    @property
    def text(self) -> str:
        return join_lines(self.lines)


@dataclass
class Entry:
    number: int
    lines: list[Line]
    issues: list[str] = field(default_factory=list)
    suffix: str = ""  # "bis", "ter": entries inserted after numbering was fixed

    @property
    def label(self) -> str:
        return f"{self.number}{self.suffix}"

    @property
    def text(self) -> str:
        return join_lines(self.lines)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(LOOKALIKES)
    for rx, repl in HEADING_REPAIRS:
        text = rx.sub(repl, text)
    return re.sub(r"(?<=\w)·(?=\s|$)", ".", text)


def join_lines(lines: list[Line]) -> str:
    """Join OCR lines, undoing end-of-line hyphenation."""
    out = ""
    for line in lines:
        raw = line.text
        piece = raw.strip()
        if not piece:
            continue
        if not out:
            out = piece
        elif re.search(r"[a-zà-ÿ]-\s?$", out_raw) and piece[:1].islower():
            out = out.rstrip()[:-1] + piece  # "Ar- / denne" -> "Ardenne"
        elif not out_raw.endswith((" ", "\t")) and re.search(r"[a-zà-ÿ]$", out_raw) and piece[:1].islower():
            out += piece  # soft hyphen lost by OCR: "opgra / vingen" -> "opgravingen"
        else:
            out += " " + piece
        out_raw = raw
    return re.sub(r"\s{2,}", " ", out).strip()


def heading_key(text: str) -> str:
    """Normalised heading text without numbering, notes and punctuation, for fuzzy matching."""
    text = normalise(text).lower()
    text = re.sub(r"\((?:\d|[xl*»i])\)", " ", text)
    text = re.sub(r"^\s*(?:[ivx]{1,4}|[a-k]|\d{1,2})\s?[.)]\s*", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def known_headings(jats_dir: str) -> list[str]:
    parser = etree.XMLParser(load_dtd=False, no_network=True, recover=True)
    keys: set[str] = set()
    for path in glob.glob(str(Path(jats_dir) / "BGB_*.xml")):
        root = etree.parse(path, parser).getroot()
        for title in root.iter("title"):
            if title.getparent() is not None and title.getparent().tag == "ref-list":
                key = heading_key("".join(title.itertext()))
                if len(key) >= 6:
                    keys.add(key)
    return sorted(keys)


# --------------------------------------------------------------------------- PDF


def year_ranges(reader: PdfReader) -> dict[str, tuple[int, int]]:
    """Map year -> (first, last) 0-based page indices, from the PDF outline."""
    tops = [o for o in reader.outline if not isinstance(o, list)]
    starts = [(o.title.strip(), reader.get_destination_page_number(o)) for o in tops]
    ranges = {}
    for k, (title, start) in enumerate(starts):
        end = starts[k + 1][1] - 1 if k + 1 < len(starts) else len(reader.pages) - 1
        ranges[title] = (start, end)
    return ranges


def outline_titles(reader: PdfReader, year: str) -> list[tuple[str, int]]:
    """(title, depth) of the sections in the 'Plan' branch of one year's outline."""
    items = list(reader.outline)
    for k, item in enumerate(items):
        if not isinstance(item, list) and item.title.strip() == year:
            children = items[k + 1] if k + 1 < len(items) and isinstance(items[k + 1], list) else []
            break
    else:
        return []
    titles, inside_plan = [], False

    def walk(nodes, depth=1):
        for node in nodes:
            if isinstance(node, list):
                walk(node, depth + 1)
            else:
                titles.append((node.title.strip(), depth))

    for k, node in enumerate(children):
        if isinstance(node, list):
            if inside_plan:
                walk(node)
            continue
        inside_plan = node.title.strip() == "Plan"
    return [(t, d) for t, d in titles if not t.lower().startswith("abréviations")]


def read_cover(text: str) -> dict:
    meta = {}
    if m := re.search(r"In:\s*(.+?)\.\s*Tome\s+(\d+)\s+fasc\.\s*(\d+),\s*(\d{4})", text, re.S):
        meta.update(journal=" ".join(m.group(1).split()), volume=m.group(2), issue=m.group(3), pub_year=m.group(4))
    if m := re.search(r"pp\.\s*(\d+)\s*-\s*(\d+)", text):
        meta.update(fpage=m.group(1), lpage=m.group(2))
    if m := re.search(r"(https?://www\.persee\.fr/\S+)", text):
        meta["persee_url"] = m.group(1)
    if m := re.search(r"Citer ce document / Cite this document :\s*(.+?)\s*In:", text, re.S):
        meta["cite_as"] = " ".join(m.group(1).split())
    return meta


def load_lines(reader: PdfReader, first: int, last: int) -> tuple[str, list[Line]]:
    cover, lines = "", []
    for i in range(first, last + 1):
        text = reader.pages[i].extract_text() or ""
        if "Citer ce document" in text:
            cover = cover or text
            continue
        print_page = None
        for raw in text.split("\n"):
            if m := RUNNING_HEADER.match(raw):
                print_page = int(m.group(1) or m.group(2))
                continue
            lines.append(Line(i + 1, print_page, raw))
        # the first page of a year has no running header: infer from the next one
    for k, line in enumerate(lines):
        if line.print_page is None:
            nxt = next((l for l in lines[k:] if l.print_page is not None and l.pdf_page != line.pdf_page), None)
            if nxt is not None:
                line.print_page = nxt.print_page - (nxt.pdf_page - line.pdf_page)
    return cover, lines


# --------------------------------------------------------------------------- segmentation


def heading_style(text: str) -> str | None:
    for style, rx in (
        ("roman", HEADING_ROMAN),
        ("upper", HEADING_UPPER),
        ("digit_paren", HEADING_DIGIT_PAREN),
        ("digit_dot", HEADING_DIGIT_DOT),
        ("lower", HEADING_LOWER),
    ):
        if rx.match(normalise(text)):
            return style
    return None


def best_match(key: str, candidates: list[str]) -> int:
    if not key or not candidates:
        return 0
    return max(fuzz.partial_ratio(key, c) if len(key) >= 12 else fuzz.ratio(key, c) for c in candidates)


def best_ratio(key: str, candidates: list[str]) -> int:
    """Whole-string similarity, ignoring candidates of very different length."""
    pool = [c for c in candidates if 0.6 * len(key) <= len(c) <= 1.6 * len(key)]
    return max((fuzz.ratio(key, c) for c in pool), default=0)


def outline_match(key: str, outline: list[tuple[str, int]]) -> tuple[int, int | None]:
    """Best (score, depth) of a heading against the outline titles."""
    best = (0, None)
    for title_key, depth in outline:
        score = best_match(key, [title_key])
        if score > best[0]:
            best = (score, depth)
    return best


def segment(lines: list[Line], outline: list[tuple[str, int]], dictionary: list[str]):
    outline_keys = [(heading_key(t), d) for t, d in outline]
    blocks: list[Entry | Heading] = []
    footnotes: list[list[Line]] = []
    last: int | None = None  # number of the previous entry
    started = False  # becomes True at the first outline heading; front matter before it is dropped
    footnote_page = None
    prev_text = ""
    last_upper = ""  # letter of the last "A." / "B." heading

    for line in lines:
        text = normalise(line.text)
        if not text.strip():
            continue
        # footnotes run from "(1) ..." to the end of the page
        if footnote_page == line.pdf_page:
            footnotes[-1].append(line)
            continue
        if started and FOOTNOTE_START.match(text) and ENDS_ENTRY.search(prev_text):
            footnote_page = line.pdf_page
            footnotes.append([line])
            continue

        # entry start: the next expected number (digits may be split by OCR: "641 3")
        if m := ENTRY_START.match(text):
            number = int(m.group(1) + m.group(2))
            plausible = started and (last is None or 0 < number - last <= 3)
            if not plausible and m.group(2) and last is not None:
                number = int(m.group(1))
                plausible = 0 < number - last <= 3
            body = text[m.end():]
            if plausible:
                blocks.append(Entry(number, [Line(line.pdf_page, line.print_page, body)]))
                last = number
                prev_text = text
                continue
            if started and number == last and (b := BIS.match(body)):
                entry = Entry(number, [Line(line.pdf_page, line.print_page, body[b.end():])], suffix=b.group(1))
                blocks.append(entry)
                prev_text = text
                continue
        # garbled number ("6305" for 6385, "71 1 1", "θ552") right after a completed entry
        if started and last is not None and ENDS_ENTRY.search(prev_text) and (m := FUZZY_NUMBER.match(text)):
            digits = m.group(1).translate(OCR_DIGITS).replace(" ", "")
            for number in () if digits == str(last) else range(last + 1, last + 4):
                target = str(number)
                if len(digits) == len(target) and sum(a != b for a, b in zip(digits, target)) <= 1:
                    entry = Entry(number, [Line(line.pdf_page, line.print_page, text[m.end():])])
                    entry.issues.append(f"number-ocr-repaired:{m.group(1).strip()}")
                    blocks.append(entry)
                    last = number
                    break
            else:
                number = None
            if number is not None:
                prev_text = text
                continue

        # heading start
        style = heading_style(text)
        key = heading_key(text)
        after_heading = bool(blocks) and isinstance(blocks[-1], Heading)
        after_entry = bool(blocks) and isinstance(blocks[-1], Entry) and ENDS_ENTRY.search(prev_text)
        # "I." / "V." / "X." may be the letter following "H." / "U." / "W." rather than a roman numeral
        if style == "roman" and last_upper and key and text.strip()[0] == chr(ord(last_upper) + 1):
            style = "upper"
        is_heading = False
        depth = None
        if style in ("roman", "upper"):
            score, depth = outline_match(key, outline_keys)
            is_heading = score >= 85
            if not is_heading and started and (after_entry or after_heading):
                # sections below the depth the outline covers (e.g. I.–IV. under "F. Époque contemporaine")
                depth = None
                is_heading = best_ratio(key, dictionary) >= 75
        elif not started:
            is_heading = False
        elif style in ("digit_paren", "digit_dot", "lower"):
            is_heading = bool(after_entry or after_heading) and (best_match(key, dictionary) >= 80 or " — " in text)
        elif after_entry and len(key) >= 8 and not text.lstrip().startswith(("—", "-")) and not CITATION_LIKE.search(text):
            # unnumbered heading: must closely match a heading known from neighbouring volumes;
            # lines directly after a heading are its continuation (wrapped or Dutch half)
            is_heading = best_ratio(key, dictionary) >= 88

        if is_heading:
            started = True
            if style == "upper":
                last_upper = text.strip()[0]
            blocks.append(Heading(style or "plain", [line], outline_level=depth))
            prev_text = text
            continue

        # continuation of the current block (front matter before the first heading is dropped)
        if blocks:
            blocks[-1].lines.append(line)
        prev_text = text
    return blocks, footnotes


def assign_levels(blocks) -> None:
    """Give headings a depth.

    Headings found in the PDF outline take their outline depth. Below that, a
    numbering style seen earlier on the current path is a sibling of that
    heading; a new style opens a deeper level. Unnumbered headings follow the
    same rule. This is a best-effort reconstruction, to be checked by an editor.
    """
    stack: list[tuple[str, int, bool]] = []  # (style, level, from outline) along the current path
    for block in blocks:
        if not isinstance(block, Heading):
            continue
        style = block.style
        # a heading that is not in the outline is never a sibling of one that is
        same = [k for k, (st, _, outl) in enumerate(stack) if st == style and not outl]
        if block.outline_level:
            level = block.outline_level
            stack = [x for x in stack if x[1] < level]
        elif same:
            level = stack[same[-1]][1]
            stack = stack[: same[-1]]
        else:
            level = stack[-1][1] + 1 if stack else 1
        stack.append((style, level, bool(block.outline_level)))
        block.level = level


def check_entries(blocks) -> list[int]:
    entries = [b for b in blocks if isinstance(b, Entry)]
    missing = []
    for a, b in zip(entries, entries[1:]):
        missing.extend(range(a.number + 1, b.number))
    for entry in entries:
        text = entry.text
        if len(text) > 1500:
            entry.issues.append("very-long")
        if len(text) < 25:
            entry.issues.append("very-short")
        if re.search(r"\s(?:[IVX]{1,4}|[A-H])\.\s+[A-ZÉ]{4,}", text):
            entry.issues.append("may-contain-heading")
    return missing


# --------------------------------------------------------------------------- output


def to_jats(year: str, meta: dict, blocks, footnotes, provenance: dict) -> etree._ElementTree:
    article = etree.Element("article", nsmap={"xlink": "http://www.w3.org/1999/xlink"})
    article.set("article-type", "bibliography")
    article.set("{http://www.w3.org/XML/1998/namespace}lang", "fr")
    front = etree.SubElement(article, "front")
    jmeta = etree.SubElement(front, "journal-meta")
    jtg = etree.SubElement(jmeta, "journal-title-group")
    etree.SubElement(jtg, "journal-title").text = meta.get("journal", "Revue belge de philologie et d'histoire")
    ameta = etree.SubElement(front, "article-meta")
    etree.SubElement(ameta, "article-id", {"pub-id-type": "bgb-year"}).text = year
    tg = etree.SubElement(ameta, "title-group")
    etree.SubElement(tg, "article-title").text = (
        f"Bibliographie de l'histoire de Belgique — Bibliografie van de geschiedenis van België {year}"
    )
    if meta.get("pub_year"):
        etree.SubElement(etree.SubElement(ameta, "pub-date", {"pub-type": "ppub"}), "year").text = meta["pub_year"]
    for tag in ("volume", "issue", "fpage", "lpage"):
        if meta.get(tag):
            etree.SubElement(ameta, tag).text = meta[tag]
    if meta.get("persee_url"):
        etree.SubElement(ameta, "self-uri", {"{http://www.w3.org/1999/xlink}href": meta["persee_url"]})
    cmg = etree.SubElement(ameta, "custom-meta-group")
    for name, value in provenance.items():
        cm = etree.SubElement(cmg, "custom-meta")
        etree.SubElement(cm, "meta-name").text = name
        etree.SubElement(cm, "meta-value").text = str(value)

    back = etree.SubElement(article, "back")
    parents = {0: back}
    current = back
    for block in blocks:
        if isinstance(block, Heading):
            parent = parents[max(k for k in parents if k < block.level)]
            reflist = etree.SubElement(parent, "ref-list")
            etree.SubElement(reflist, "title").text = block.text
            parents = {k: v for k, v in parents.items() if k < block.level}
            parents[block.level] = reflist
            current = reflist
        else:
            first = block.lines[0]
            ref = etree.SubElement(current, "ref", {"id": f"ref{block.label}"})
            ref.set("specific-use", f"pdf-page:{first.pdf_page} print-page:{first.print_page}")
            if block.issues:
                ref.set("content-type", "check:" + ",".join(block.issues))
            etree.SubElement(ref, "label").text = block.label
            etree.SubElement(ref, "mixed-citation", {"publication-type": "unknown"}).text = block.text
    if footnotes:
        group = etree.SubElement(back, "fn-group")
        for k, fn in enumerate(footnotes, 1):
            el = etree.SubElement(group, "fn", {"id": f"fn{k}"})
            el.set("specific-use", f"pdf-page:{fn[0].pdf_page} print-page:{fn[0].print_page}")
            etree.SubElement(el, "p").text = join_lines(fn)
    return etree.ElementTree(article)


def convert(pdf: Path, year: str, headings_from: str, out: Path) -> dict:
    reader = PdfReader(str(pdf))
    first, last = year_ranges(reader)[year]
    cover, lines = load_lines(reader, first, last)
    meta = read_cover(cover)
    blocks, footnotes = segment(lines, outline_titles(reader, year), known_headings(headings_from))
    assign_levels(blocks)
    missing = check_entries(blocks)
    entries = [b for b in blocks if isinstance(b, Entry)]
    provenance = {
        "source-file": pdf.name,
        "source-sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "source-pdf-pages": f"{first + 1}-{last + 1}",
        "method": "bhb.ingest.persee_pdf (pypdf text layer, rule-based segmentation)",
        "inline-markup": "none",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    to_jats(year, meta, blocks, footnotes, provenance).write(
        str(out), xml_declaration=True, encoding="utf-8", pretty_print=True
    )
    report = {
        "year": year,
        "entries": len(entries),
        "first": entries[0].number if entries else None,
        "last": entries[-1].number if entries else None,
        "missing_numbers": missing,
        "headings": [("  " * (b.level - 1)) + b.text for b in blocks if isinstance(b, Heading)],
        "footnotes": len(footnotes),
        "flagged": {e.label: e.issues for e in entries if e.issues},
        "bis_entries": [e.label for e in entries if e.suffix],
        **{k: v for k, v in meta.items() if k != "cite_as"},
    }
    out.with_suffix(".report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("year")
    ap.add_argument("--headings-from", required=True, help="directory with STRAIVE BGB_*.xml of the same era")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    report = convert(args.pdf, args.year, args.headings_from, args.out)
    print(
        f"{report['year']}: {report['entries']} entries ({report['first']}–{report['last']}), "
        f"{len(report['missing_numbers'])} numbers absent, {len(report['headings'])} headings, "
        f"{report['footnotes']} footnotes, {len(report['flagged'])} flagged"
    )


if __name__ == "__main__":
    main()
