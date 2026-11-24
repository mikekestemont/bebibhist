"""The editor's Word manuscripts of the years not printed (2019–2023; 2018 as a print proof): ``BGBBHB<year>….docx``.

The editor keeps each year as one Word file in the old print layout: a bilingual notice, then one paragraph per
entry under bold, bilingual headings, then the tables of contents (lines ending on a tab and a page number). Since
2016 the entries are not numbered.

The layout marks what the printed text leaves to guesswork: the authors are bold, the title is italic, and in a
chapter the book's title is the second italic span. The rule parser (``bhb.parse.citation``) reads each entry, and
the formatting then sets the title, the book of a chapter and the authors where they disagree; every such change
is flagged on the record.

An entry has no printed number, so its id is a hash of its text, ``bhb:<year>-m<10 hex digits>`` (``m`` for
manuscript, so it cannot be taken for a printed number; a second entry with the same text adds ``-2``). An entry
added to a revised manuscript does not move the others' ids, as a number by position would. An entry whose text the
editor corrects gets a new id; the V-Smart record that will later replace the entry has its own id anyway.

Each heading is matched to a code of the BHB scheme by its label (``HeadingCodes``), and its entries carry that code
in ``bhb_codes``, as the catalogue's records do.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from rapidfuzz import fuzz

from bhb.model import Host, Person, Provenance, Publisher, Record, Series
from bhb.parse.citation import (
    ParsedCitation,
    _confidence,
    _parse_imprint,
    _take_trailing_brackets,
    _tidy,
    parse_citation,
)
from bhb.paths import rel
from bhb.scheme import SchemeEntry, load_scheme
from bhb.textutil import clean_heading, fold, squash

SOURCE = "manuscript"
PARSER = "manuscript-rules@0.1"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_YEAR_FILE = re.compile(r"(?:BGB|BHB)\D{0,4}(?:BGB|BHB)?\D{0,2}((?:19|20)\d{2})", re.IGNORECASE)
# "I. Bibliographies…", "A. …", "1. …", "a. …", "a.1. …"
_NUMBERED = re.compile(r"^(?:[IVX]{1,4}|[A-Z]|\d{1,2}|[a-z])(?:\.\d{1,2})*\.\s+\S")
_FIRST_HEADING = re.compile(r"^I\.\s+\S")
_TOC_LINE = re.compile(r"\t\s*\d{1,4}\s*$")
_TOC_TITLE = re.compile(r"^(?:Table des matières|Inhoudstafel|Inhoudsopgave|Inhoud)\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:1[5-9]|20)\d{2}\b")
_IN = re.compile(r"\bIn\s*:\s*")
_STAND_IN = "Zzqx"
_PAGE_RANGE = re.compile(r"\bpp?\.\s*[\dIVXLCivxlc]+(?:\s*[-–]\s*[\dIVXLCivxlc]+)?\s*$|\[?\bs\.\s?p\.\]?\s*$")
_EXTENT = re.compile(r"\b\d+\s*p\.\s*$|\[s\.p\.\]")
# The journal ends at the first comma followed by a volume, an issue or a year: "Le Moyen Âge, 126, 2020, …".
_JOURNAL_END = re.compile(r",\s*(?=(?:[IVXLCDM]+|\d+[a-z]?(?:\s*[-/]\s*\d+)?|(?:19|20)\d{2})\s*(?:,|\(|$))")
_THEME_AFTER_PAGES = re.compile(r"(\bpp?\.\s*[\dIVXLCivxlc]+(?:\s*[-–]\s*[\dIVXLCivxlc]+)?)\s*(\(.+\))\s*$")
_PAGES_TAIL = re.compile(r",?\s*(pp?\.\s*.+|\[?s\.\s?p\.\]?)$")
_YEAR_PART = re.compile(r"((?:19|20)\d{2})(?:\s*\([^)]*\))?")


def _article_tail(body: str) -> tuple[str, str | None, int | None, str | None, str | None] | None:
    """Journal, volume, year, issue and pages of an article's tail ("Journal, 42, 2020, 4, pp. 99-113"), or None.
    The volume is the number before the year, the issue the one after it."""
    match = _JOURNAL_END.search(body)
    if not match:
        return None
    host = _tidy(body[: match.start()])
    rest = body[match.end():]
    pages_match = _PAGES_TAIL.search(rest)
    pages = re.sub(r"^pp?\.\s*", "", pages_match.group(1)).strip(" .") if pages_match else None
    numbers = [part.strip() for part in (rest[: pages_match.start()] if pages_match else rest).split(",") if part.strip()]
    year_at = next((i for i, part in enumerate(numbers) if _YEAR_PART.fullmatch(part)), None)
    if not host or year_at is None:
        return None
    volume = ", ".join(numbers[:year_at]) or None
    issue = ", ".join(numbers[year_at + 1:]) or None
    if pages and re.fullmatch(r"\[?s\.\s?p\.\]?", pages):
        if not (volume or issue):
            return None  # "Place, Publisher, 2020, [s.p.]" is a book
        pages = None
    year = int(_YEAR_PART.fullmatch(numbers[year_at]).group(1))
    return host, volume, year, issue, pages


@dataclass
class Paragraph:
    text: str
    runs: list[tuple[str, bool, bool]] = field(default_factory=list)  # (text, bold, italic)


@dataclass
class Block:
    kind: str  # "heading" or "entry"
    paragraph: Paragraph


def _on(prop: etree._Element | None, name: str) -> bool:
    if prop is None:
        return False
    element = prop.find(_W + name)
    return element is not None and element.get(_W + "val") not in ("0", "false", "none")


def read_docx(path: Path) -> list[Paragraph]:
    """The non-empty paragraphs of a .docx with their runs. Bold and italic are the run's own marks; the
    manuscripts set them directly, not through character styles."""
    with zipfile.ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"), etree.XMLParser(huge_tree=True))
    paragraphs: list[Paragraph] = []
    for node in root.iter(_W + "p"):
        runs: list[tuple[str, bool, bool]] = []
        for run in node.iter(_W + "r"):
            # Text moved with tracked changes stands at its old place too, marked as moved away; deleted text is not read
            # at all (Word keeps it in another element).
            if any(parent.tag == _W + "moveFrom" for parent in run.iterancestors()):
                continue
            text = "".join(
                "\t" if child.tag == _W + "tab" else "-" if child.tag == _W + "noBreakHyphen" else (child.text or "")
                for child in run
                if child.tag in (_W + "t", _W + "tab", _W + "noBreakHyphen")
            )
            if text:
                prop = run.find(_W + "rPr")
                runs.append((text, _on(prop, "b"), _on(prop, "i")))
        text = "".join(piece for piece, _bold, _italic in runs)
        if text.strip():
            paragraphs.append(Paragraph(text, runs))
    return paragraphs


def _all_bold(paragraph: Paragraph) -> bool:
    """Every run with a letter or digit is bold; a dash or a space set otherwise ("a. Généralités – Algemeenheden"
    with an italic, not bold, dash) does not count."""
    visible = [(text, bold) for text, bold, _italic in paragraph.runs if re.search(r"\w", text)]
    return bool(visible) and all(bold for _text, bold in visible)


def _starts_bold(paragraph: Paragraph) -> bool:
    first = next(((text, bold) for text, bold, _italic in paragraph.runs if text.strip()), None)
    return bool(first and first[1])


def is_heading(paragraph: Paragraph) -> bool:
    text = paragraph.text.strip()
    if len(text) >= 300:
        return False
    if _all_bold(paragraph):
        return True
    # Some headings are not bold: numbered, bilingual ("2. Méthodologie – Methodologie"), no year. An entry starts
    # with its author, not with a number.
    return bool(_NUMBERED.match(text) and " – " in text and not _YEAR.search(text))


def segment(paragraphs: list[Paragraph]) -> list[Block]:
    """Headings and entries between the notice and the tables of contents."""
    start = next((i for i, p in enumerate(paragraphs) if _FIRST_HEADING.match(p.text.strip()) and is_heading(p)), 0)
    blocks: list[Block] = []
    for paragraph in paragraphs[start:]:
        text = paragraph.text.strip()
        if _TOC_LINE.search(paragraph.text) or _TOC_TITLE.match(text):
            break
        if is_heading(paragraph):
            previous = blocks[-1] if blocks else None
            # The Dutch half of a heading can stand in a paragraph of its own under the French half.
            if (previous is not None and previous.kind == "heading" and " – " not in previous.paragraph.text
                    and not _NUMBERED.match(text)):
                merged = f"{previous.paragraph.text.strip()} – {text}"
                previous.paragraph = Paragraph(merged, previous.paragraph.runs + [(" – ", True, False), *paragraph.runs])
                continue
            blocks.append(Block("heading", paragraph))
        else:
            blocks.append(Block("entry", paragraph))
    return blocks


def _spans(paragraph: Paragraph, bold: bool) -> list[tuple[int, int]]:
    """Character spans of the bold (or italic) runs; runs of spaces and punctuation between two marked runs join
    them, so a word set in roman inside an italic title does not end it unless it holds letters."""
    spans: list[tuple[int, int]] = []
    current: list[int] | None = None
    position = 0
    for text, is_bold, is_italic in paragraph.runs:
        marked = is_bold if bold else is_italic
        end = position + len(text)
        if marked:
            if current is None:
                current = [position, end]
            else:
                current[1] = end
        elif current is not None and text.strip(" .,:;'’‘\"«»()–-"):
            spans.append((current[0], current[1]))
            current = None
        position = end
    if current is not None:
        spans.append((current[0], current[1]))
    return spans


_NAME = re.compile(r"\s*(?:,|;|\bet\b|\ben\b|&)?\s*([^,;()]+?)\s*\(([^)]*)\)((?:\s*\([^)]*\))*)")
_EDITOR_ROLE = re.compile(r"^(?:[ée]ds?|r[ée]ds?|dir|hrsg|co[oö]rd|a cura di|ed\. lit|eindred)\.?$", re.IGNORECASE)
# The roles of the AI pass that the schema lacks (``bhb.citations._PARSER_ROLES``).
_OTHER_ROLES = (
    (re.compile(r"^(?:pr[ée]face|preface|voorwoord|vorwort|inleiding|introduction|avant-propos)\.?$", re.IGNORECASE), "preface"),
    (re.compile(r"^(?:ill|illustr|illustrations?|illustraties)\.?$", re.IGNORECASE), "illustrator"),
    (re.compile(r"^(?:comp|compil|samenst|samengesteld)\.?$", re.IGNORECASE), "compiler"),
)


def bold_names(prefix: str) -> list[dict[str, str | None]]:
    """The names of a bold author prefix: "van de Venne (Hans), Snoek (Govert) (medewerker)." The manuscripts
    always give "Family (Given)", so a lowercase particle ("de Waha (Michel)") is read as part of the family name;
    a mark in a second bracket after it ("(ed.)", "(red.)", "(dir.)") makes the person an editor."""
    persons: list[dict[str, str | None]] = []
    rest = prefix.strip().rstrip(".").strip()
    while rest:
        match = _NAME.match(rest)
        if not match:
            return persons if not rest.strip(" .,") else []
        family, given = squash(match.group(1)), squash(match.group(2)) or None
        marks = [squash(m) for m in re.findall(r"\(([^)]*)\)", match.group(3))]
        if not family or len(family.split()) > 6:
            return []
        if given and _EDITOR_ROLE.match(given):  # "Redactie (red.)": no given name, only the mark
            marks.append(given)
            given = None
        role = "editor" if any(_EDITOR_ROLE.match(mark) for mark in marks) else "author"
        for pattern, other in _OTHER_ROLES:
            if any(pattern.match(mark) for mark in marks):
                role = other
        if role == "editor":
            # "M'Bokolo (Elikia), Sabakinu Kivilu (Jacob) (dir.)": the mark covers the names before it that have none.
            for earlier in reversed(persons):
                if earlier.get("marked"):
                    break
                earlier["role"] = "editor"
        persons.append({"family": family, "given": given, "role": role, "marked": bool(marks)})
        rest = rest[match.end():].strip()
    for person in persons:
        del person["marked"]
    return persons


def _same(left: str | None, right: str | None) -> bool:
    return fold(left or "").strip(" .") == fold(right or "").strip(" .")


def parse_entry(paragraph: Paragraph) -> ParsedCitation:
    """The rule parser's reading, corrected by the formatting."""
    text = paragraph.text
    parsed = parse_citation(text)
    if parsed.is_cross_listing:
        return parsed
    bold = _spans(paragraph, bold=True)
    italic = _spans(paragraph, bold=False)
    # Authors: the bold prefix, when it parses as names and the rules found other ones.
    if bold and bold[0][0] <= 2:
        persons = bold_names(text[bold[0][0]:bold[0][1]])
        if persons and [(p["family"], p["role"]) for p in persons] != [(p["family"], p["role"]) for p in parsed.persons]:
            parsed.persons = persons
            parsed.flags.append("persons-from-bold")
    if not italic:
        parsed.flags.append("no-italic-title")
        return parsed
    start, end = italic[0]
    title = _tidy(text[start:end])
    if not title:
        return parsed
    rest = text[end:]
    if _IN.match(rest.lstrip(" .")) or parsed.type == "chapter":
        if not _same(parsed.title, title):
            parsed.title = title
            parsed.flags.append("title-from-italics")
        if len(italic) > 1 and _IN.search(text[end:italic[1][0]]):
            book = _tidy(text[italic[1][0]:italic[1][1]])
            if book and not _same(parsed.host_title, book):
                parsed.host_title = book
                parsed.flags.append("host-from-italics")
        parsed.confidence = _confidence(parsed)
        return parsed
    body, trailing = _take_trailing_brackets(rest.strip())
    body = body.strip(" .")
    # A theme issue in brackets after the pages ("…, pp. 443-463 (Lembré (Stéphane) (dir.). Terres de travail …)")
    # is a note, not part of the journal.
    if themed := _THEME_AFTER_PAGES.search(body):
        trailing = _tidy(" ".join(filter(None, (themed.group(2), trailing))))
        body = body[: themed.start(2)].strip(" .")
    article = _article_tail(body) if _PAGE_RANGE.search(body) and not _EXTENT.search(body) else None
    same_title = _same(parsed.title, title)
    if same_title and (article is None or (parsed.type == "article" and _same(parsed.host_title, article[0]))):
        return parsed
    # The rules cut the title elsewhere, or read an article as something else: read what follows the italic
    # title again.
    redo = ParsedCitation(persons=parsed.persons, title=title, title_translated=parsed.title_translated)
    notes = [n for n in (trailing, parsed.note) if n]
    if article is not None:
        # An article: everything from the end of the title to the volume is the journal, full stops and commas
        # included ("Oost-Brabant. Heemkundig Tijdschrift…", "Heemkundig tijdschrift voor Huldenberg, Loonbeek, …").
        redo.type = "article"
        redo.host_title, redo.volume, redo.year, redo.issue, redo.pages = article
    else:
        # A book or other: the rules read the imprint after a stand-in title, so that "Venray, s.n., 2020" is
        # taken as place and publisher, not as a title.
        tail = parse_citation(f"{_STAND_IN}. {body}")
        leftover = _tidy((tail.title or "").replace(_STAND_IN, "", 1))
        for name in ("volume", "issue", "year", "pages", "place", "publisher", "extent", "series_title",
                     "series_number"):
            setattr(redo, name, getattr(tail, name))
        if tail.place or tail.publisher or tail.extent:
            redo.type = "book"
            if leftover:
                notes.insert(0, leftover)  # an edition or a translator between the title and the place
        else:
            host = tail.host_title or leftover
            if host:
                where = body.find(host)
                host = _tidy(body[: where + len(host)]) if where > 0 else host
            redo.host_title = host
            redo.type = "article" if host and (tail.volume or tail.pages or tail.issue) else "other"
    redo.note = _tidy(" ".join(notes)) if notes else None
    redo.series_title = redo.series_title or parsed.series_title
    redo.series_number = redo.series_number or parsed.series_number
    redo.cross_refs = parsed.cross_refs
    redo.flags = [*parsed.flags, "imprint-from-format" if same_title else "title-from-italics"]
    redo.confidence = _confidence(redo)
    return redo


_CODE_NUMBER = re.compile(r"^((?:[IVX]{1,4}|[A-Z]|\d{1,2}|[a-z])(?:\.\d{1,2})*)\.\s+")
_HALVES = re.compile(r"\s+[–-]\s+|\s+/\s+")


def _tokens(code: str) -> list[str]:
    return [token for token in code.split(".") if token]


def own_labels(scheme: dict[str, SchemeEntry]) -> dict[str, dict[str, str]]:
    """Each code's own label in French and Dutch. The scheme labels a code with its whole path ("Histoire par
    époques / Epoque contemporaine… / … / Les arts"), so the segments name the code's ancestors too; a path whose
    length does not fit the code gives only its last segment."""
    fitting: dict[str, dict[str, str]] = {}
    last_only: dict[str, dict[str, str]] = {}
    for code, entry in scheme.items():
        tokens = _tokens(code)
        for language, label in (("fr", entry.label_fr), ("nl", entry.label_nl)):
            if not label:
                continue
            segments = [segment.strip() for segment in label.split(" / ")]
            fits = len(segments) == len(tokens)
            target = fitting if fits else last_only
            for back in range(1, len(tokens) + 1) if fits else (1,):
                prefix = ".".join(tokens[: len(tokens) - back + 1]) + "."
                target.setdefault(prefix, {}).setdefault(language, segments[-back])
    for code, labels in last_only.items():
        for language, label in labels.items():
            fitting.setdefault(code, {}).setdefault(language, label)
    return fitting


def _words(text: str) -> str:
    return " ".join(re.sub(r"[;,:’'()]", " ", fold(text)).split())


def _halves(heading: str) -> tuple[str | None, str, str]:
    """The heading's number, French half and Dutch half. A dash between two numbers ("1940 – 1945") is no split."""
    match = _CODE_NUMBER.match(heading)
    number = match.group(1) if match else None
    body = heading[match.end():] if match else heading
    for split in _HALVES.finditer(body):
        left, right = body[: split.start()], body[split.end():]
        if re.search(r"[^\W\d]", left) and re.search(r"[^\W\d]", right):
            return number, left, right
    return number, body, ""


class HeadingCodes:
    """The scheme code of each heading, read in order. A heading takes the code whose own label it matches,
    preferring a code whose parent is the code of an open heading above it; its number counts only as a tie-break
    and as support for a weaker match, since the manuscripts' numbering is not always regular ("c. La
    démographie" before "b. La vie économique et sociale"). A heading that matches no code gets none, and nor do
    its entries."""

    STRONG = 80
    WEAK = 55

    def __init__(self, scheme: dict[str, SchemeEntry] | None = None):
        self.scheme = scheme if scheme is not None else load_scheme()
        self.labels = own_labels(self.scheme)
        self.open: list[str] = []

    def _score(self, french: str, dutch: str, labels: dict[str, str], scorer=fuzz.ratio) -> float:
        best = 0.0
        # "Généralités : La vie religieuse" is the code "La vie religieuse" under "Généralités".
        mines = [french, dutch, *(half.split(" : ", 1)[1] for half in (french, dutch) if " : " in half)]
        for mine in mines:
            for theirs in (labels.get("fr"), labels.get("nl")):
                if mine and theirs:
                    best = max(best, scorer(_words(mine), _words(theirs)))
        return best

    def __call__(self, heading: str) -> str | None:
        number, french, dutch = _halves(heading)
        last = number.split(".")[-1] if number else None
        best: tuple[tuple[int, float], str, float] | None = None
        for code, labels in self.labels.items():
            score = self._score(french, dutch, labels)
            parent = self.scheme[code].parent if code in self.scheme else None
            depth = next((i + 1 for i in range(len(self.open) - 1, -1, -1) if parent == self.open[i]), 0)
            context = -1 if parent is not None and depth == 0 else depth
            fits = last is not None and _tokens(code)[-1] == last
            # Number and parent agreeing, the label may name only part of the code's ("3. Théorie" for "Théorie et
            # histoire").
            # A heading may also name one part of a code that joins two ("a. Histoire diplomatique" and "b. Les
            # explorations…" for "Histoire diplomatique; les explorations…"), under the right parent.
            overlap = self._score(french, dutch, labels, fuzz.token_set_ratio) if context > 0 else 0.0
            loose = (fits and overlap >= self.STRONG) or overlap >= 95
            if not (score >= self.STRONG or (fits and context > 0 and score >= self.WEAK) or loose):
                continue
            key = (context, score + (10 if fits else 0))
            if best is None or key > best[0]:
                best = (key, code, score)
        if best is None or (best[0][0] < 0 and best[2] < 90):
            return None
        code = best[1]
        self.open = [open_code for open_code in self.open if code.startswith(open_code) and open_code != code] + [code]
        return code


def code_sections(records: list[Record], scheme: dict[str, SchemeEntry] | None = None) -> int:
    """Give the records of one printed volume, in order, the scheme code of their deepest heading (``HeadingCodes``),
    as the manuscripts' entries get theirs: the volumes from 2009 number their headings as irregularly. Returns how
    many records got a code."""
    codes = HeadingCodes(scheme)
    previous: list[str] = []
    current: str | None = None
    coded = 0
    for record in records:
        path = list(record.section_path)
        if path != previous:
            shared = 0
            while shared < min(len(path), len(previous)) and path[shared] == previous[shared]:
                shared += 1
            current = None if shared < len(path) else current
            for heading in path[shared:]:
                current = codes(heading)
            previous = path
        if current and not record.bhb_codes:
            record.bhb_codes = [current]
            coded += 1
    return coded


def year_of(path: Path) -> int | None:
    match = _YEAR_FILE.search(path.stem)
    return int(match.group(1)) if match else None


def _xml_id(text: str, seen: dict[str, int]) -> str:
    digest = hashlib.sha1(squash(text).encode("utf-8")).hexdigest()[:10]
    seen[digest] = seen.get(digest, 0) + 1
    return digest if seen[digest] == 1 else f"{digest}-{seen[digest]}"


def _record(parsed: ParsedCitation, text: str, year: int, path: Path, xml_id: str,
            section: list[str]) -> Record:
    record = Record(
        id=f"bhb:{year}-m{xml_id}",
        source=SOURCE,
        bgb_year=year,
        printed=squash(text),
        section_path=list(section),
        provenance=Provenance(file=rel(path), xml_id=xml_id, parser=PARSER, flags=["unpublished-manuscript"]),
    )
    record.type = parsed.type
    record.title = parsed.title
    record.title_translated = parsed.title_translated
    record.persons = [
        Person(family=p["family"] or "", given=p.get("given"), role=p.get("role") or "author")
        for p in parsed.persons
        if p.get("family")
    ]
    record.year = parsed.year
    record.extent = parsed.extent
    record.note = parsed.note
    record.is_cross_listing = parsed.is_cross_listing
    if any((parsed.host_title, parsed.volume, parsed.issue, parsed.pages)):
        record.host = Host(title=parsed.host_title, volume=parsed.volume, issue=parsed.issue,
                           year=str(parsed.year) if parsed.year else None, pages=parsed.pages)
    if parsed.place or parsed.publisher:
        record.publisher = Publisher(place=parsed.place, name=parsed.publisher)
    if parsed.series_title or parsed.series_number:
        record.series = Series(title=parsed.series_title, number=parsed.series_number)
    record.provenance.confidence = parsed.confidence
    record.provenance.flags.extend(parsed.flags)
    record.provenance.flags = list(dict.fromkeys(record.provenance.flags))
    return record


def load_manuscript(path: Path, year: int | None = None, scheme: dict[str, SchemeEntry] | None = None) -> tuple[list[Record], dict]:
    """One manuscript → records, and a report of what was read."""
    year = year or year_of(path)
    if year is None:
        raise ValueError(f"no BGB year in the file name {path.name}; pass it")
    blocks = segment(read_docx(path))
    codes = HeadingCodes(scheme)
    open_headings: list[tuple[str, str]] = []  # (code, heading) of the headings above
    code: str | None = None
    seen: dict[str, int] = {}
    records: list[Record] = []
    for block in blocks:
        text = block.paragraph.text
        if block.kind == "heading":
            heading = clean_heading(squash(text))
            if not heading:
                continue
            code = codes(heading)
            if code is not None:
                open_headings = [(c, h) for c, h in open_headings if c and code.startswith(c) and c != code]
                open_headings.append((code, heading))
            else:
                # An unmatched heading stands in the path of its entries, which get no code; it closes at the
                # next heading.
                open_headings = [(c, h) for c, h in open_headings if c] + [("", heading)]
            continue
        parsed = parse_entry(block.paragraph)
        section = [heading for _code, heading in open_headings]
        record = _record(parsed, text, year, path, _xml_id(text, seen), section)
        if code:
            record.bhb_codes = [code]
        records.append(record)
    flags = ("title-from-italics", "imprint-from-format", "host-from-italics", "persons-from-bold", "no-italic-title")
    report = {
        "file": path.name,
        "year": year,
        "entries": len(records),
        "headings": sum(block.kind == "heading" for block in blocks),
        "types": {kind: sum(r.type == kind for r in records) for kind in ("article", "chapter", "book", "other")},
        "below_0.6": sum(r.provenance.confidence < 0.6 for r in records),
        "without a code": sum(not r.bhb_codes for r in records),
        **({"tracked changes": marks} if (marks := tracked(path)) else {}),
        **{flag: sum(flag in r.provenance.flags for r in records) for flag in flags},
    }
    return records, report


def manuscript_paths(folder: Path) -> list[Path]:
    """The manuscripts in ``folder``, one per year. A file whose name gives no year, and two files of one year (two
    versions, or a Word file and its proof), stop the reading: by name alone the wrong one would win, or a year would
    be read twice. The one not to read goes to ``superseded/``."""
    by_year: dict[int, list[Path]] = {}
    for path in sorted([*folder.glob("*.docx"), *folder.glob("*.pdf"), *folder.glob("*.doc")]):
        if path.name.startswith("~$"):
            continue
        year = year_of(path)
        if year is None:
            raise ValueError(f"{path.name}: no BGB year in the name (name it like BGBBHB2022.docx, or move it to superseded/)")
        if path.suffix == ".doc":
            raise ValueError(f"{path.name}: the old Word format; save it as .docx")
        by_year.setdefault(year, []).append(path)
    for year, paths in by_year.items():
        if len(paths) > 1:
            raise ValueError(f"{year}: {len(paths)} files ({', '.join(path.name for path in paths)}); keep the one to read, move the others to superseded/")
    return [by_year[year][0] for year in sorted(by_year) if by_year[year][0].suffix == ".docx"]


def tracked(path: Path) -> dict[str, int]:
    """What a .docx still holds of the editing: tracked insertions, deletions and moves, and comments."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return {name: n for name, tag in (("inserted", "ins"), ("deleted", "del"), ("moved", "moveFrom"), ("comments", "commentReference"))
            if (n := len(re.findall(rf"<w:{tag}[ >/]", xml)))}
