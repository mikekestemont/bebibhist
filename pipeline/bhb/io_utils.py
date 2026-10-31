"""JSON Lines helpers for ``build/``."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from bhb.model import (
    Category,
    Host,
    PdfLink,
    Person,
    Provenance,
    Publisher,
    Record,
    Series,
)


def write_jsonl(path: Path, records: Iterable[Record]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False))
            handle.write("\n")
            count += 1
    return count


def read_jsonl(path: Path) -> list[Record]:
    records: list[Record] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(record_from_dict(json.loads(line)))
    return records


def _host(data: dict | None) -> Host | None:
    if not data:
        return None
    raw = dict(data)
    editors = [Person(**person) for person in raw.pop("editors", None) or []]
    publisher = raw.pop("publisher", None)
    return Host(editors=editors, publisher=Publisher(**publisher) if publisher else None, **raw)


def _category(data: dict) -> Category:
    return Category(
        code=data.get("code"),
        source=data.get("source") or "",
        confidence=float(data.get("confidence") or 0),
        machine=bool(data.get("machine")),
        primary=bool(data.get("primary")),
        theme=data.get("theme"),
    )


def record_from_dict(data: dict) -> Record:
    persons = [Person(**person) for person in data.get("persons") or []]
    host = _host(data.get("host"))
    series = Series(**data["series"]) if data.get("series") else None
    publisher = Publisher(**data["publisher"]) if data.get("publisher") else None
    pdf = PdfLink(**data["pdf"]) if data.get("pdf") else None
    provenance = Provenance(**(data.get("provenance") or {}))
    return Record(
        id=data["id"],
        source=data["source"],
        bgb_year=data.get("bgb_year"),
        print_number=data.get("print_number"),
        printed=data.get("printed"),
        type=data.get("type") or "other",
        title=data.get("title"),
        subtitle=data.get("subtitle"),
        title_translated=data.get("title_translated"),
        persons=persons,
        corporate=list(data.get("corporate") or []),
        host=host,
        series=series,
        publisher=publisher,
        year=data.get("year"),
        extent=data.get("extent"),
        note=data.get("note"),
        language=data.get("language"),
        section_path=list(data.get("section_path") or []),
        secondary_sections=[list(item) for item in data.get("secondary_sections") or []],
        bhb_codes=list(data.get("bhb_codes") or []),
        categories=[_category(item) for item in data.get("categories") or []],
        theme=list(data.get("theme") or []),
        period=list(data.get("period") or []),
        places=list(data.get("places") or []),
        place_ids=list(data.get("place_ids") or []),
        place_suggested=list(data.get("place_suggested") or []),
        cross_refs=list(data.get("cross_refs") or []),
        links=list(data.get("links") or []),
        is_cross_listing=bool(data.get("is_cross_listing")),
        role=data.get("role") or "entry",
        pdf=pdf,
        provenance=provenance,
        similar=list(data.get("similar") or []),
        similar_scores=[float(score) for score in data.get("similar_scores") or []],
        theme_suggested=list(data.get("theme_suggested") or []),
        period_suggested=list(data.get("period_suggested") or []),
    )
