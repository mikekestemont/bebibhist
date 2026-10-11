"""Write the semantic record as MODS 3.8, one collection per BGB year.

The printed citation is copied unchanged into ``note[@type='printed citation']``.
Structured fields are the ones the parsers stored. Machine-derived values stay
distinguishable: the period facet uses ``authority="bhb-period"``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lxml import etree

from bhb.io_utils import record_from_dict
from bhb.model import Record

NS = "http://www.loc.gov/mods/v3"
XLINK = "http://www.w3.org/1999/xlink"
DATA_LICENCE = "CC BY-NC 4.0"
DATA_LICENCE_URL = "https://creativecommons.org/licenses/by-nc/4.0/"
ROLES = {
    "author": "aut",
    "editor": "edt",
    "compiler": "com",
    "translator": "trl",
    "illustrator": "ill",
    "preface": "aui",
}
_PAGE_RANGE = re.compile(r"^(.+?)\s*[-–—]\s*(.+)$")


def export_mods(jsonl: Path, out_dir: Path) -> dict[str, int]:
    """Stream ``records.jsonl`` into ``bhb-<year>.xml``. Records without a year go to ``bhb-hosts.xml``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    handles: dict[str, object] = {}
    counts: dict[str, int] = {}

    def bucket(key: str):
        if key not in handles:
            handle = (out_dir / f"bhb-{key}.xml").open("w", encoding="utf-8")
            handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
            handle.write(f'<modsCollection xmlns="{NS}">\n')
            handles[key] = handle
            counts[key] = 0
        return handles[key]

    with jsonl.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            record = record_from_dict(json.loads(line))
            key = str(record.bgb_year) if record.bgb_year else "hosts"
            handle = bucket(key)
            handle.write(etree.tostring(to_mods(record), encoding="unicode"))
            handle.write("\n")
            counts[key] += 1
    for handle in handles.values():
        handle.write("</modsCollection>\n")
        handle.close()
    return counts


def to_mods(record: Record) -> etree._Element:
    mods = etree.Element(f"{{{NS}}}mods", nsmap={None: NS, "xlink": XLINK})
    _title(mods, record.title, record.subtitle, None)
    if record.title_translated:
        _title(mods, record.title_translated, None, "translated")
    for person in record.persons:
        _person(mods, person.family, person.given, person.role)
    for body in record.corporate:
        name = _sub(mods, "name", type="corporate")
        _text(_sub(name, "namePart"), body)
    if record.publisher or record.year:
        origin = _sub(mods, "originInfo")
        if record.publisher and record.publisher.place:
            place = _sub(origin, "place")
            _text(_sub(place, "placeTerm", type="text"), record.publisher.place)
        if record.publisher and record.publisher.name:
            _text(_sub(origin, "publisher"), record.publisher.name)
        if record.year:
            _text(_sub(origin, "dateIssued"), str(record.year))
    if record.extent:
        physical = _sub(mods, "physicalDescription")
        _text(_sub(physical, "extent"), record.extent)
    if record.host and any((record.host.title, record.host.volume, record.host.issue, record.host.pages, record.host.id)):
        _host(mods, record)
    if record.series and (record.series.title or record.series.number):
        _series(mods, record)
    if record.note:
        _text(_sub(mods, "note", type="annotation"), record.note)
    if record.section_path:
        _text(_sub(mods, "note", type="section"), " — ".join(record.section_path))
    coded = [category for category in record.categories if category.code]
    if coded:
        for category in coded:
            attrib = {"authority": "bhb"}
            if category.primary:
                attrib["usage"] = "primary"
            if category.machine:
                attrib["displayLabel"] = "machine-suggested"
            _text(_sub(mods, "classification", **attrib), category.code or "")
    else:
        for code in record.bhb_codes:
            _text(_sub(mods, "classification", authority="bhb"), code)
    for period in record.period:
        _text(_sub(mods, "classification", authority="bhb-period"), period)
    for place in record.places:
        subject = _sub(mods, "subject")
        _text(_sub(subject, "geographic"), place)
    for target in record.cross_refs:
        related = _sub(mods, "relatedItem", type="references")
        _text(_sub(related, "identifier", type="bhb"), target)
    if record.type:
        _text(_sub(mods, "genre", authority="local"), record.type)
    if record.language:
        language = _sub(mods, "language")
        _text(_sub(language, "languageTerm", type="code"), record.language)
    for link in record.links:
        location = _sub(mods, "location")
        _text(_sub(location, "url"), link)
    if record.pdf and record.pdf.url:
        location = _sub(mods, "location")
        _text(_sub(location, "url"), record.pdf.url)
    _text(_sub(mods, "identifier", type="bhb"), record.id)
    info = _sub(mods, "recordInfo")
    _text(_sub(info, "recordIdentifier", source="bhb"), record.id)
    _text(_sub(info, "recordContentSource"), _content_source(record))
    _text(_sub(info, "recordOrigin"), _origin(record))
    if record.printed:
        _text(_sub(mods, "note", type="printed citation"), record.printed)
    condition = _sub(mods, "accessCondition", type="use and reproduction")
    condition.set(f"{{{XLINK}}}href", DATA_LICENCE_URL)
    _text(condition, DATA_LICENCE)
    return mods


def _title(parent: etree._Element, title: str | None, subtitle: str | None, kind: str | None) -> None:
    if not title and not subtitle:
        return
    info = _sub(parent, "titleInfo", **({"type": kind} if kind else {}))
    if title:
        _text(_sub(info, "title"), title)
    if subtitle:
        _text(_sub(info, "subTitle"), subtitle)


def _person(parent: etree._Element, family: str, given: str | None, role: str) -> None:
    name = _sub(parent, "name", type="personal")
    _text(_sub(name, "namePart", type="family"), family)
    if given:
        _text(_sub(name, "namePart", type="given"), given)
    role_el = _sub(name, "role")
    code = ROLES.get(role, "aut")
    _text(_sub(role_el, "roleTerm", authority="marcrelator", type="code"), code)


def _host(parent: etree._Element, record: Record) -> None:
    host = record.host
    assert host is not None
    related = _sub(parent, "relatedItem", type="host")
    _title(related, host.title, host.subtitle, None)
    for person in host.editors:
        _person(related, person.family, person.given, person.role or "editor")
    if host.id:
        _text(_sub(related, "identifier", type="bhb"), host.id)
    part = _sub(related, "part")
    if host.volume:
        detail = _sub(part, "detail", type="volume")
        _text(_sub(detail, "number"), host.volume)
    if host.issue:
        detail = _sub(part, "detail", type="issue")
        _text(_sub(detail, "number"), host.issue)
    if host.pages:
        extent = _sub(part, "extent", unit="pages")
        match = _PAGE_RANGE.match(host.pages)
        if match and "p." not in host.pages.lower():
            _text(_sub(extent, "start"), match.group(1))
            _text(_sub(extent, "end"), match.group(2))
        else:
            extent.text = host.pages


def _series(parent: etree._Element, record: Record) -> None:
    series = record.series
    assert series is not None
    related = _sub(parent, "relatedItem", type="series")
    if series.title:
        info = _sub(related, "titleInfo")
        _text(_sub(info, "title"), series.title)
    if series.number:
        part = _sub(related, "part")
        detail = _sub(part, "detail", type="volume")
        _text(_sub(detail, "number"), series.number)


def _content_source(record: Record) -> str:
    if record.bgb_year and record.print_number:
        text = f"BGB-BHB {record.bgb_year}, no. {record.print_number}"
        if record.pdf and record.pdf.print_page:
            text = f"{text}, p. {record.pdf.print_page}"
        return text
    if record.source == "vsmart":
        number = record.id.removeprefix("bhb:vs-")
        return f"ARA V-Smart record {number}"
    return record.id


def _origin(record: Record) -> str:
    parser = record.provenance.parser or "bhb"
    flags = ",".join(record.provenance.flags)
    text = f"{parser} confidence={record.provenance.confidence:.2f}"
    if flags:
        text = f"{text} flags={flags}"
    return text


def _sub(parent: etree._Element, tag: str, **attrib: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{NS}}}{tag}", attrib=attrib)


def _text(element: etree._Element, value: str) -> None:
    element.text = value
