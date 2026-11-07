"""BHB record, version 0. The JSON object written to ``build/records.jsonl``."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


@dataclass
class Person:
    family: str
    given: str | None = None
    role: str = "author"
    # An ORCID iD, machine-derived: "openalex" (from the entry's DOI) or "name" (from another entry by this name).
    orcid: str | None = None
    orcid_from: str | None = None
    # From KBR's Belgian Bibliography, machine-derived: the given name written out where the entry prints initials,
    # the dates ("1922-2013"), KBR's authority id, and where it came from: "kbr" (the entry's own book, matched to
    # KBR) or "kbr-name" (this name on another entry, when it can only be that person).
    given_full: str | None = None
    dates: str | None = None
    kbr_id: str | None = None
    name_from: str | None = None


@dataclass
class Host:
    title: str | None = None
    id: str | None = None
    volume: str | None = None
    issue: str | None = None
    year: str | None = None
    pages: str | None = None
    subtitle: str | None = None
    editors: list[Person] = field(default_factory=list)
    publisher: Publisher | None = None


@dataclass
class Series:
    title: str | None = None
    number: str | None = None


@dataclass
class Publisher:
    place: str | None = None
    name: str | None = None


@dataclass
class PdfLink:
    file: str | None = None
    page: int | None = None
    print_page: int | None = None
    url: str | None = None


@dataclass
class Category:
    """One code or, when the code is uncertain, one theme. ``machine`` is true unless a person or the printed volume set it."""

    code: str | None = None
    source: str = ""
    confidence: float = 0.0
    machine: bool = False
    primary: bool = False
    theme: str | None = None


@dataclass
class Provenance:
    file: str | None = None
    xml_id: str | None = None
    vendor_type: str | None = None
    label_raw: str | None = None
    parser: str = ""
    confidence: float = 0.0
    flags: list[str] = field(default_factory=list)


@dataclass
class Record:
    id: str
    source: str
    bgb_year: int | None
    print_number: str | None = None
    printed: str | None = None
    type: str = "other"
    title: str | None = None
    subtitle: str | None = None
    title_translated: str | None = None
    # Machine translations of the title (with subtitle) into the languages of nl, fr and en it is not in
    # (``bhb citations apply``): for search only, never shown.
    translations: dict[str, str] = field(default_factory=dict)
    # Words of the printed text the citation pass read as OCR errors, corrected ("Dcndcrmonde" → "Dendermonde"):
    # for search only, never shown; the printed text stays as it is. About one in eight is wrong.
    ocr_corrected: list[str] = field(default_factory=list)
    persons: list[Person] = field(default_factory=list)
    corporate: list[str] = field(default_factory=list)
    host: Host | None = None
    series: Series | None = None
    publisher: Publisher | None = None
    year: int | None = None
    extent: str | None = None
    note: str | None = None
    language: str | None = None
    section_path: list[str] = field(default_factory=list)
    secondary_sections: list[list[str]] = field(default_factory=list)
    bhb_codes: list[str] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)
    theme: list[str] = field(default_factory=list)
    period: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    # Per place: ``nis:<code>`` from ``data/curated/gazetteer.csv``, or ``name:<printed name>`` when it is not there.
    place_ids: list[str] = field(default_factory=list)
    # Places in ``place_ids`` that a machine found in the title, not the printed index.
    place_suggested: list[str] = field(default_factory=list)
    # Identifiers found by matching (``bhb identifiers apply``), never printed: the DOI, ISBNs, ISSNs, and per
    # identifier the source that gave it ("crossref" or "vabb").
    doi: str | None = None
    isbn: list[str] = field(default_factory=list)
    issn: list[str] = field(default_factory=list)
    identifiers_from: dict[str, str] = field(default_factory=dict)
    # The KBR record of the book, or of a chapter's volume (``uurl.kbr.be/bib/<number>``); its source in
    # ``identifiers_from["kbr"]``.
    kbr: str | None = None
    # True when the DOI leads to a free copy (OpenAlex, or Persée); the link stays the DOI.
    free_to_read: bool | None = None
    # The journal of an article (``bhb journals apply``): "issn:<ISSN>" or "t:<title>"; see data/curated/journals.csv.
    journal_id: str | None = None
    cross_refs: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    is_cross_listing: bool = False
    role: str = "entry"
    pdf: PdfLink | None = None
    provenance: Provenance = field(default_factory=Provenance)
    similar: list[str] = field(default_factory=list)
    similar_scores: list[float] = field(default_factory=list)
    # Values in ``theme`` and ``period`` that a machine suggested, not a person or the printed volume.
    theme_suggested: list[str] = field(default_factory=list)
    period_suggested: list[str] = field(default_factory=list)
    # Languages of publication (ISO 639-1) a machine read in the title (``bhb language apply``), the main title's
    # first; a second one only for a title in two languages, never for the editors' bracketed translation.
    language_suggested: list[str] = field(default_factory=list)
    # The entry's place on the topic map, in the unit square, and its finest region there (``bhb topicmap``).
    topic_xy: list[float] = field(default_factory=list)
    topic: str | None = None
    # Ids this entry had in earlier builds (a repaired printed number), so old links still find it (``bhb/ids.py``).
    former_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))
