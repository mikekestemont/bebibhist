"""Read one BGB year of JATS (STRAIVE tags, or plain text from a PDF conversion)."""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from bhb.labels import repair_labels
from bhb.model import Host, PdfLink, Person, Provenance, Publisher, Record, Series
from bhb.parse.citation import cross_references, parse_citation
from bhb.paths import rel
from bhb.sections import path_of, push_heading
from bhb.textutil import clean_heading, squash, superscript

XML = etree.XMLParser(load_dtd=False, no_network=True, recover=True, resolve_entities=False, huge_tree=True)
_YEAR_FILE = re.compile(r"BGB_((?:19|20)\d{2})\.xml$")
_EDITOR = re.compile(r"\((?:éds?|eds?|réd|red|dir)\.?\)", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)((?:1[5-9]|20)\d{2})(?!\d)")
_EXTENT = re.compile(r"(\d+\s*p\.|s\.p\.)", re.IGNORECASE)
_SPECIFIC = re.compile(r"pdf-page:(\d+)(?:\s+print-page:(\d+))?")
_DASH = re.compile(r"\s[—–]\s")

_DECADE = (
    (1952, 1959, "BGB_1952-59"),
    (1960, 1969, "BGB_1960-69"),
    (1970, 1979, "BGB_1970-79"),
    (1980, 1989, "BGB_1980-89"),
    (1990, 1999, "BGB_1990-99"),
    (2000, 2007, "BGB_2000-07"),
    (2008, 2008, "BGB_2008"),
)


def straive_paths(root: Path) -> list[Path]:
    found = []
    for path in sorted((root / "2023-12-29").glob("BGB_*/*.xml")):
        if _YEAR_FILE.search(path.name):
            found.append(path)
    return found


def year_of(path: Path) -> int:
    match = _YEAR_FILE.search(path.name)
    if not match:
        raise ValueError(f"not a yearly BGB file: {path.name}")
    return int(match.group(1))


def pdf_link(year: int, page: int | None = None, print_page: int | None = None) -> PdfLink:
    name = next(label for start, end, label in _DECADE if start <= year <= end)
    url = f"https://www.rbph-btfg.be/dowload_PDFs/{name}.php"
    if page:
        url = f"{url}#page={page}"
    return PdfLink(file=f"{name}.pdf", page=page, print_page=print_page, url=url)


def load_jats(path: Path, source: str) -> list[Record]:
    """One XML file → records. Nothing is dropped because a field failed to parse."""
    year = year_of(path)
    root = etree.parse(str(path), XML).getroot()
    back = root.find("back")
    if back is None:
        return []
    stack: list[tuple[int, str]] = []
    pending: list[tuple[Record, list[tuple[int | None, str]]]] = []
    for element in back.iter():
        parent = element.getparent()
        if element.tag == "title" and parent is not None and parent.tag == "ref-list":
            heading = clean_heading(_plain(element))
            if heading:
                stack = push_heading(stack, heading)
            continue
        if element.tag != "ref":
            continue
        record, raw_refs = _ref_to_record(element, year, path, source, path_of(stack))
        pending.append((record, raw_refs))
    _apply_labels(pending)
    records = [record for record, _refs in pending]
    known = {record.id for record in records}
    for record, raw_refs in pending:
        record.cross_refs = []
        for ref_year, number in raw_refs:
            target = f"bhb:{ref_year or year}-{number}"
            record.cross_refs.append(target)
            if target not in known:
                record.provenance.flags.append("cross-ref-unresolved")
        record.provenance.flags = list(dict.fromkeys(record.provenance.flags))
    return records


def _apply_labels(pending: list[tuple[Record, list]]) -> None:
    raws = [record.print_number or "" for record, _refs in pending]
    seen: dict[str, int] = {}
    for (record, _refs), (number, repaired) in zip(pending, repair_labels(raws)):
        record.provenance.label_raw = record.print_number
        record.print_number = number or record.print_number
        if repaired:
            record.provenance.flags.append("label-repaired")
        base = f"bhb:{record.bgb_year}-{record.print_number}"
        if base in seen:
            seen[base] += 1
            record.id = f"{base}-dup{seen[base]}"
            record.provenance.flags.append("duplicate-id")
        else:
            seen[base] = 1
            record.id = base


def _ref_to_record(
    ref: etree._Element,
    year: int,
    path: Path,
    source: str,
    section_path: list[str],
) -> tuple[Record, list[tuple[int | None, str]]]:
    label = squash(ref.findtext("label") or "")
    citation = ref.find("mixed-citation")
    printed = _plain(citation) if citation is not None else ""
    page, print_page = _pdf_pages(ref.get("specific-use"))
    flags = _check_flags(ref.get("content-type"))
    record = Record(
        id=f"bhb:{year}-{label or 'unnumbered'}",
        source=source,
        bgb_year=year,
        print_number=label or None,
        printed=printed or None,
        section_path=list(section_path),
        pdf=pdf_link(year, page, print_page),
        provenance=Provenance(
            file=rel(path),
            xml_id=ref.get("id"),
            vendor_type=citation.get("publication-type") if citation is not None else None,
            label_raw=label or None,
            parser="jats-rules@0.1",
            flags=flags,
        ),
    )
    if citation is None or not printed:
        record.provenance.flags.append("no-citation")
        record.provenance.confidence = 0.05
        return record, []
    children = [child for child in citation if isinstance(child.tag, str)]
    if not children:
        return _from_plain_text(record, printed)
    return _from_tags(record, citation, printed)


def _from_plain_text(record: Record, printed: str) -> tuple[Record, list]:
    parsed = parse_citation(printed)
    record.type = parsed.type
    record.title = parsed.title
    record.title_translated = parsed.title_translated
    record.persons = [
        Person(family=person["family"] or "", given=person.get("given"), role=person.get("role") or "author")
        for person in parsed.persons
        if person.get("family")
    ]
    record.year = parsed.year
    record.extent = parsed.extent
    record.note = parsed.note
    record.is_cross_listing = parsed.is_cross_listing
    if any((parsed.host_title, parsed.volume, parsed.issue, parsed.pages)):
        record.host = Host(
            title=parsed.host_title,
            volume=parsed.volume,
            issue=parsed.issue,
            year=str(parsed.year) if parsed.year else None,
            pages=parsed.pages,
        )
    if parsed.place or parsed.publisher:
        record.publisher = Publisher(place=parsed.place, name=parsed.publisher)
    if parsed.series_title or parsed.series_number:
        record.series = Series(title=parsed.series_title, number=parsed.series_number)
    record.provenance.parser = "citation-rules@0.1"
    record.provenance.confidence = parsed.confidence
    record.provenance.flags.extend(parsed.flags)
    return record, list(parsed.cross_refs)


def _from_tags(record: Record, citation: etree._Element, printed: str) -> tuple[Record, list]:
    article_title: list[str] = []
    chapter_title: list[str] = []
    translated: list[str] = []
    sources: list[str] = []
    persons: list[Person] = []
    corporate: list[str] = []
    volume = issue = fpage = lpage = place = publisher = year_text = None
    links: list[str] = []
    note_parts: list[str] = []
    seen_imprint = False
    note_mode = False
    author_blob: list[str] = []
    host_editors: list[Person] = []
    collecting_authors = False
    title_seen = False

    for child in citation:
        text = squash(_plain(child))
        tail = child.tail or ""
        if child.tag == "person-group":
            grouped = _persons(child)
            # An editor group after the title belongs to the work named after "In:", not to the chapter.
            if title_seen and child.get("person-group-type") == "editor":
                host_editors.extend(grouped)
            else:
                collecting_authors = True
                persons.extend(grouped)
                author_blob.append(_plain(child))
        elif child.tag == "collab":
            if text:
                corporate.append(text)
        elif child.tag == "etal":
            record.provenance.flags.append("et-al")
        elif child.tag == "article-title" and text:
            article_title.append(text)
            collecting_authors = False
            title_seen = True
        elif child.tag == "chapter-title" and text:
            chapter_title.append(text)
            collecting_authors = False
            title_seen = True
        elif child.tag == "trans-title" and text:
            translated.append(text)
        elif child.tag == "source" and text:
            if note_mode:
                note_parts.append(text)
            else:
                sources.append(text)
            collecting_authors = False
        elif child.tag == "volume":
            volume = text or volume
            seen_imprint = True
        elif child.tag == "issue":
            issue = text or issue
            seen_imprint = True
        elif child.tag == "year":
            year_text = text or year_text
            seen_imprint = True
        elif child.tag == "fpage":
            fpage = text or fpage
            seen_imprint = True
        elif child.tag == "lpage":
            lpage = text or lpage
            seen_imprint = True
        elif child.tag == "publisher-loc":
            place = text or place
        elif child.tag == "publisher-name":
            publisher = text or publisher
        elif child.tag == "uri":
            link = _link(child)
            if link:
                links.append(link)
        if collecting_authors and tail:
            author_blob.append(tail)
        if seen_imprint and not note_mode and _DASH.search(tail):
            note_mode = True
            note_parts.append(_DASH.split(tail, maxsplit=1)[1])
        elif note_mode and tail.strip():
            note_parts.append(tail)

    if _EDITOR.search(" ".join(author_blob)):
        for person in persons:
            person.role = "editor"
    year = int(_YEAR.search(year_text).group(1)) if year_text and _YEAR.search(year_text) else None
    pages = _pages(fpage, lpage)
    has_volume = bool(volume or issue or fpage)
    has_publisher = bool(publisher)
    in_chapter = bool(chapter_title) or bool(re.search(r"\bIn\s*:", printed))
    if in_chapter:
        record.type = "chapter"
    elif article_title and sources and has_volume and not has_publisher:
        record.type = "article"
    elif (place or publisher) and not (article_title and has_volume):
        record.type = "book"
    elif article_title and sources and has_volume:
        record.type = "article"
    else:
        record.type = "other"

    first_source = sources[0] if sources else None
    if record.type in {"article", "chapter"}:
        record.title = _join(chapter_title or article_title) or first_source
        record.host = Host(
            title=first_source if (chapter_title or article_title) else None,
            volume=volume,
            issue=issue,
            year=str(year) if year else None,
            pages=pages,
        )
    elif record.type == "book":
        record.title = _join(article_title) or first_source
        if article_title and first_source and first_source not in (record.title or ""):
            record.title = f"{record.title}. {first_source}"
    else:
        record.title = _join(article_title or chapter_title) or first_source
        if article_title and first_source:
            record.host = Host(title=first_source, volume=volume, issue=issue, pages=pages, year=str(year) if year else None)
    record.title_translated = _join(translated)
    record.persons = persons
    record.corporate = corporate
    record.year = year
    if place or publisher:
        record.publisher = Publisher(place=place, name=publisher)
    record.links = list(dict.fromkeys(links))
    if record.type == "book" and not pages:
        if match := _EXTENT.search(printed):
            record.extent = match.group(1)
    if note_parts:
        record.note = squash(" ".join(note_parts)).strip(" .") or None
    if record.type == "book" and record.host and not record.host.pages:
        record.host = None
    if record.host is not None and host_editors:
        record.host.editors = host_editors

    raw: list[tuple[int | None, str]] = []
    record.title, found = _strip_refs(record.title)
    raw.extend(found)
    record.title_translated, found = _strip_refs(record.title_translated)
    raw.extend(found)
    record.note, found = _strip_refs(record.note)
    raw.extend(found)
    _printed_clean, found = cross_references(printed)
    for ref in found:
        if ref not in raw:
            raw.append(ref)
    letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", _printed_clean)
    if raw and len(letters) < 12:
        record.is_cross_listing = True
    record.provenance.confidence = _confidence(record)
    return record, raw


def _persons(group: etree._Element) -> list[Person]:
    people: list[Person] = []
    for name in group.findall("string-name"):
        family = squash(_plain(name.find("surname"))) if name.find("surname") is not None else ""
        given_el = name.find("given-names")
        given = squash(_plain(given_el)) if given_el is not None and squash(_plain(given_el)) else None
        if family:
            role = "editor" if group.get("person-group-type") == "editor" else "author"
            people.append(Person(family=family, given=given, role=role))
    return people


def _link(element: etree._Element) -> str | None:
    href = (
        element.get("{http://www.w3.org/1999/xlink}href")
        or element.get("href")
        or element.get("type")
        or ""
    )
    text = squash(element.text or "")
    for candidate in (href, text):
        value = squash(candidate)
        if value.startswith(("http://", "https://", "www.")):
            return value
    return None


def _pages(fpage: str | None, lpage: str | None) -> str | None:
    if fpage and lpage and lpage not in fpage:
        return f"{fpage}–{lpage}"
    return fpage or lpage


def _join(parts: list[str]) -> str | None:
    text = squash(" ".join(part for part in parts if part))
    return text or None


def _strip_refs(text: str | None) -> tuple[str | None, list[tuple[int | None, str]]]:
    if not text:
        return text, []
    cleaned, found = cross_references(text)
    cleaned = squash(cleaned).strip(" .[]")
    return (cleaned or None), found


def _confidence(record: Record) -> float:
    score = 0.4
    if record.title:
        score += 0.2
    if record.persons or record.corporate:
        score += 0.15
    if record.year:
        score += 0.1
    if record.type in {"article", "chapter"} and record.host and record.host.title:
        score += 0.1
    if record.type == "book" and record.publisher and (record.publisher.place or record.publisher.name):
        score += 0.1
    if (record.host and record.host.pages) or record.extent:
        score += 0.05
    if record.type == "other":
        score -= 0.05
    score -= 0.03 * len(record.provenance.flags)
    return round(max(0.05, min(0.98, score)), 2)


def _plain(element: etree._Element | None) -> str:
    if element is None:
        return ""
    return squash(_node_text(element))


def _node_text(element: etree._Element) -> str:
    parts: list[str] = []
    if element.text:
        parts.append(element.text)
    for child in element:
        if not isinstance(child.tag, str):
            continue
        if child.tag == "sup":
            parts.append(superscript("".join(child.itertext())))
        else:
            parts.append(_node_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _pdf_pages(specific: str | None) -> tuple[int | None, int | None]:
    if not specific:
        return None, None
    match = _SPECIFIC.search(specific)
    if not match:
        return None, None
    print_page = int(match.group(2)) if match.group(2) else None
    return int(match.group(1)), print_page


def _check_flags(content_type: str | None) -> list[str]:
    if not content_type or not content_type.startswith("check:"):
        return []
    return [flag for flag in content_type.removeprefix("check:").split(",") if flag]

