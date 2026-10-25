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
    cross_refs: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    is_cross_listing: bool = False
    role: str = "entry"
    pdf: PdfLink | None = None
    provenance: Provenance = field(default_factory=Provenance)
    similar: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))
