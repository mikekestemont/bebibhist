"""Adapter for the State Archives V-Smart UNIMARC exports (BGB 2009–2017)."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from lxml import etree

from bhb.model import Host, Person, Provenance, Publisher, Record, Series
from bhb.textutil import squash

# f1450 is 2009 … f1440 is 2017. f1442 is unused. f1441 is the journal file.
FILE_YEAR = {
    "f1450.xml": 2009,
    "f1449.xml": 2010,
    "f1448.xml": 2011,
    "f1447.xml": 2012,
    "f1446.xml": 2013,
    "f1445.xml": 2014,
    "f1444.xml": 2015,
    "f1443.xml": 2016,
    "f1440.xml": 2017,
}
JOURNAL_FILE = "f1441.xml"

_CODE = re.compile(r"^((?:[IVX]+|[A-Za-z]|\d+)(?:\.(?:[A-Za-z]|\d+))*)\.\s+(.+)$")
_FR = re.compile(r"Histoire|époque|Époque|Travaux|secteur|Auxiliaire|générale|Bibliographie", re.IGNORECASE)
_NL = re.compile(r"Geschiedenis|tijdvak|Werken|Hedendaagse|Algemene|Bibliografie", re.IGNORECASE)
_ACCENT = re.compile(r"[éèêëàâùûôîïç]")
_HOST = re.compile(r"(?:Bib:)?2[:^](\d+)")
_YEAR = re.compile(r"(?<!\d)((?:1[5-9]|20)\d{2})(?!\d)")
_PAGES = re.compile(r"p{1,2}\.\s*([0-9][\d\s\-–]*)", re.IGNORECASE)
_VOLUME = re.compile(r"jg\.\s*([IVXLCDM]+|\d+)", re.IGNORECASE)
_ISSUE = re.compile(r"nr\.\s*([\d/\-–]+)", re.IGNORECASE)
_RECORD = "BibDocumentsUniMarcB.Record"

_ROLES = (
    ("onder leiding", "editor"),
    ("samensteller", "compiler"),
    ("uitgever", "compiler"),
    ("voorwoord", "preface"),
    ("nawoord", "preface"),
    ("vertaler", "translator"),
    ("illustrator", "illustrator"),
    ("auteur", "author"),
)


def load_vsmart(directory: Path) -> tuple[list[Record], dict[str, dict[str, str | None]]]:
    """Yearly exports plus the journal file. Repeated record ids are merged."""
    labels: dict[str, dict[str, str | None]] = {}
    by_id: dict[str, Record] = {}
    order: list[str] = []
    for name, year in FILE_YEAR.items():
        path = directory / name
        if not path.is_file():
            continue
        for record, found in _file_records(path, year, journals=False):
            _remember(by_id, order, record)
            _remember_labels(labels, found)
    journal_path = directory / JOURNAL_FILE
    if journal_path.is_file():
        for record, found in _file_records(journal_path, None, journals=True):
            _remember(by_id, order, record)
            _remember_labels(labels, found)
    return [by_id[key] for key in order], labels


def _remember(by_id: dict[str, Record], order: list[str], record: Record) -> None:
    current = by_id.get(record.id)
    if current is None:
        by_id[record.id] = record
        order.append(record.id)
        return
    record.provenance.flags.append("merged-duplicate")
    current.provenance.flags.append("merged-duplicate")
    if _richness(record) > _richness(current):
        record.provenance.flags = list(dict.fromkeys(record.provenance.flags))
        by_id[record.id] = record


def _richness(record: Record) -> int:
    return sum(
        1
        for value in (
            record.title,
            record.subtitle,
            record.printed,
            record.year,
            record.extent,
            record.host and record.host.id,
            record.publisher and record.publisher.name,
        )
        if value
    ) + len(record.persons) + len(record.bhb_codes) + len(record.corporate)


def _remember_labels(labels: dict[str, dict[str, str | None]], found: dict[str, dict[str, str]]) -> None:
    for code, names in found.items():
        slot = labels.setdefault(code, {"label_nl": None, "label_fr": None})
        slot["label_nl"] = slot["label_nl"] or names.get("nl")
        slot["label_fr"] = slot["label_fr"] or names.get("fr")


def _file_records(path: Path, file_year: int | None, journals: bool):
    for _event, element in etree.iterparse(
        str(path), events=("end",), tag=_RECORD, recover=True, huge_tree=True
    ):
        record, found = _convert(element, path, file_year, journals)
        yield record, found
        element.clear()


def _convert(element: etree._Element, path: Path, file_year: int | None, journals: bool):
    fields: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for child in element:
        if not isinstance(child.tag, str) or child.tag == "Trefwoorden":
            continue
        text = squash(child.text or "")
        if not text:
            continue
        try:
            count = int(child.get("Cnt") or "1")
        except ValueError:
            count = 1
        fields[child.tag].append((count, text))

    raw_id = element.get("Value") or ""
    match = re.search(r"(\d+)$", raw_id)
    number = match.group(1) if match else raw_id
    codes, label_map = _codes(fields)
    bgb_year = None if journals else _bgb_year(fields, file_year)
    title = _first(fields, "_200aHoofdtitel")
    subtitle = _first(fields, "_200eAnderetitelinformatie")
    parallel = _first(fields, "_200dParallellehoofdtitel")
    material = _first(fields, "_200bAlgemenemateriaalaanduiding") or ""
    persons = _people(fields, "_700") + _people(fields, "_701")
    corporate = _corporate(fields)
    place = _first(fields, "_210a")
    publisher = _first(fields, "_210c")
    pub_year = _year_in(_first(fields, "_210dDatumvanuitgavedistributieetc.") or "")
    extent = _first(fields, "_215aSpecifiekemateriaalaanduiding")
    series_title = _first(fields, "_225aSerietitel")
    series_number = _first(fields, "_225vVolumeaanduiding")
    host_raw = _first(fields, "_4630")
    host_id = f"bhb:vs-{_HOST.search(host_raw).group(1)}" if host_raw and _HOST.search(host_raw) else None
    linkage = _first(fields, "_463vVolumenummer")
    host_bits = _parse_linkage(linkage) if linkage else {}

    if journals or material.lower().startswith("tijdschrift") or "revue" in material.lower():
        kind = "journal-issue"
    elif "artikel" in material.lower() or "article" in material.lower():
        kind = "article"
    elif material:
        kind = "other"
    else:
        kind = "book"

    host = None
    if host_id or linkage:
        host = Host(
            title=None,
            id=host_id,
            volume=host_bits.get("volume"),
            issue=host_bits.get("issue"),
            year=str(host_bits["year"]) if host_bits.get("year") else None,
            pages=host_bits.get("pages"),
        )
    printed = render_printed_fields(
        persons, title, subtitle, host, pub_year or host_bits.get("year"), extent, place, publisher
    )
    flags: list[str] = []
    if not title:
        flags.append("no-title")
    record = Record(
        id=f"bhb:vs-{number}",
        source="vsmart",
        bgb_year=bgb_year,
        printed=printed,
        type=kind,
        title=title,
        subtitle=subtitle,
        title_translated=parallel,
        persons=persons,
        corporate=corporate,
        host=host,
        series=Series(title=series_title, number=series_number) if series_title or series_number else None,
        publisher=Publisher(place=place, name=publisher) if place or publisher else None,
        year=pub_year or host_bits.get("year"),
        extent=extent,
        bhb_codes=codes,
        role="host" if journals else "entry",
        provenance=Provenance(
            file=str(path.name),
            xml_id=raw_id,
            vendor_type=material or None,
            parser="vsmart@0.1",
            confidence=0.9 if title else 0.4,
            flags=flags,
        ),
    )
    return record, label_map


def _codes(fields: dict[str, list[tuple[int, str]]]) -> tuple[list[str], dict[str, dict[str, str]]]:
    order: list[str] = []
    labels: dict[str, dict[str, str]] = {}
    for _count, text in fields.get("_686aHoofdgeleding", []):
        match = _CODE.match(text)
        if not match:
            continue
        code = match.group(1) + "."
        label = match.group(2).strip()
        if code not in labels:
            order.append(code)
            labels[code] = {}
        language = _label_language(label)
        labels[code].setdefault(language, label)
    return order, labels


def _label_language(label: str) -> str:
    french = len(_FR.findall(label))
    dutch = len(_NL.findall(label))
    if french > dutch:
        return "fr"
    if dutch > french:
        return "nl"
    if _ACCENT.search(label):
        return "fr"
    return "nl"


def _bgb_year(fields: dict[str, list[tuple[int, str]]], file_year: int | None) -> int | None:
    raw = _first(fields, "_686vCoderingjaarinBHB-BGB") or ""
    match = re.search(r"(20\d{2})", raw)
    if match and 2000 <= int(match.group(1)) <= 2030:
        return int(match.group(1))
    return file_year


def _people(fields: dict[str, list[tuple[int, str]]], prefix: str) -> list[Person]:
    surnames = {count: text for count, text in fields.get(f"{prefix}aEntryElement", [])}
    givens = {count: text for count, text in fields.get(f"{prefix}bPartofNameOtherthanEntryElement", [])}
    roles = {count: text for count, text in fields.get(f"{prefix}4Functiecode-Verwoording", [])}
    people: list[Person] = []
    for count in sorted(set(surnames) | set(givens)):
        family = surnames.get(count)
        if not family:
            continue
        people.append(Person(family=family, given=givens.get(count), role=_role(roles.get(count))))
    return people


def _corporate(fields: dict[str, list[tuple[int, str]]]) -> list[str]:
    names = {count: text for count, text in fields.get("_710aEntryElement", [])}
    parts = {count: text for count, text in fields.get("_710bSubdivision", [])}
    extra = [text for _count, text in fields.get("_711aEntryElement", [])]
    bodies = []
    for count in sorted(names):
        body = names[count]
        if count in parts:
            body = f"{body}, {parts[count]}"
        bodies.append(body)
    return bodies + extra


def _role(text: str | None) -> str:
    if not text:
        return "author"
    lowered = text.lower()
    for needle, role in _ROLES:
        if needle in lowered:
            return role
    return "author"


def _parse_linkage(text: str) -> dict:
    found: dict = {}
    if match := _YEAR.search(text):
        found["year"] = int(match.group(1))
    if match := _VOLUME.search(text):
        found["volume"] = match.group(1)
    elif match := re.match(r"\s*\d{4}\s*,\s*(\d{1,4})\s*,", text):
        found["volume"] = match.group(1)
    if match := _ISSUE.search(text):
        found["issue"] = match.group(1)
    if match := _PAGES.search(text):
        found["pages"] = squash(match.group(1)).strip(" .")
    if re.search(r"s\.p\.", text, re.IGNORECASE):
        found["pages"] = found.get("pages") or "s.p."
    return found


def render_printed(record: Record) -> str:
    """Citation-like line so a catalogue record can be shown next to a printed one."""
    return render_printed_fields(
        record.persons,
        record.title,
        record.subtitle,
        record.host,
        record.year,
        record.extent,
        record.publisher.place if record.publisher else None,
        record.publisher.name if record.publisher else None,
    )


def render_printed_fields(persons, title, subtitle, host: Host | None, year, extent, place, publisher) -> str:
    names = [f"{person.family} ({person.given})" if person.given else person.family for person in persons]
    if len(names) > 1:
        authors = ", ".join(names[:-1]) + " & " + names[-1]
    else:
        authors = names[0] if names else ""
    bits: list[str] = []
    if authors:
        bits.append(authors + ".")
    heading = title or ""
    if subtitle:
        heading = f"{heading}: {subtitle}" if heading else subtitle
    if heading:
        bits.append(heading.rstrip(".") + ".")
    if host is not None:
        detail = ", ".join(
            part
            for part in (
                host.volume,
                str(year) if year else host.year,
                f"p. {host.pages}" if host.pages else None,
            )
            if part
        )
        host_name = host.title or "[host record not exported]"
        host_bit = "In: " + host_name
        if detail:
            host_bit += ", " + detail
        bits.append(_sentence(host_bit))
    else:
        imprint = ", ".join(part for part in (place, publisher, str(year) if year else None, extent) if part)
        if imprint:
            bits.append(_sentence(imprint))
    return " ".join(bits)


def _sentence(text: str) -> str:
    text = text.rstrip()
    return text if text.endswith(".") else text + "."


def _first(fields: dict[str, list[tuple[int, str]]], tag: str) -> str | None:
    values = fields.get(tag)
    if not values:
        return None
    return values[0][1]


def _year_in(text: str) -> int | None:
    match = _YEAR.search(text)
    return int(match.group(1)) if match else None
