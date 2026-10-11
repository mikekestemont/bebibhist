"""Combine the three adapters into ``build/records.jsonl`` and an ingest report."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from bhb.facets import assign_period
from bhb.ingest.vsmart import render_printed
from bhb.model import Person, Record
from bhb.sections import is_part_heading

HOST_MISSING = "[host record not exported]"


def merge_records(
    straive: list[Record],
    pdf: list[Record],
    vsmart: list[Record],
    code_labels: dict[str, dict[str, str | None]] | None = None,
) -> tuple[list[Record], dict[str, dict[str, str | None]]]:
    records = [*straive, *pdf, *vsmart]
    by_id = {record.id: record for record in records}
    referenced: set[str] = set()
    for record in records:
        host = record.host
        if host is None or not host.id:
            continue
        referenced.add(host.id)
        target = by_id.get(host.id)
        if target is None:
            if not host.title:
                host.title = HOST_MISSING
            record.provenance.flags.append("host-unresolved")
            continue
        if not host.title:
            host.title = target.title
        if not host.subtitle and target.subtitle:
            host.subtitle = target.subtitle
        if not host.editors:
            host.editors = [
                Person(person.family, person.given, person.role)
                for person in target.persons
                if person.role == "editor"
            ]
        if record.type == "article" and target.type == "book":
            record.type = "chapter"
        elif record.type == "article" and target.type == "journal-issue":
            record.type = "article"
    for record in records:
        if record.source == "vsmart" and not record.bhb_codes and record.id in referenced:
            record.role = "host"
        record.period = assign_period(record.section_path, record.bhb_codes)
        record.provenance.flags = list(dict.fromkeys(record.provenance.flags))
        if record.source == "vsmart":
            record.printed = render_printed(record)
    labels = code_labels or {}
    return records, labels


def write_scheme(path: Path, records: list[Record], labels: dict[str, dict[str, str | None]]) -> None:
    counts: Counter[str] = Counter()
    for record in records:
        if record.role != "entry" or record.is_cross_listing:
            continue
        for code in record.bhb_codes:
            counts[code] += 1
    codes = set(counts) | set(labels)
    for code in list(codes):
        parent = _parent(code)
        while parent:
            codes.add(parent)
            parent = _parent(parent)
    rows = []
    for code in sorted(codes):
        names = labels.get(code, {})
        rows.append(
            {
                "code": code,
                "parent": _parent(code),
                "label_nl": names.get("label_nl"),
                "label_fr": names.get("label_fr"),
                "count": counts.get(code, 0),
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def write_report(path: Path, records: list[Record]) -> None:
    by_year: dict[int | None, Counter[str]] = {}
    flags: Counter[str] = Counter()
    repairs = 0
    unresolved_hosts = 0
    for record in records:
        bucket = by_year.setdefault(record.bgb_year, Counter())
        bucket[record.source] += 1
        if record.is_cross_listing:
            bucket["cross-listing"] += 1
        if record.role == "host":
            bucket["host"] += 1
        flags.update(record.provenance.flags)
        if "label-repaired" in record.provenance.flags:
            repairs += 1
        if "host-unresolved" in record.provenance.flags:
            unresolved_hosts += 1
    lines = [
        "# Ingest report",
        "",
        f"Records: **{len(records)}**.",
        f"Search hits (entries that are not cross-listing stubs and not host records): "
        f"**{sum(1 for r in records if r.role == 'entry' and not r.is_cross_listing)}**.",
        f"Label repairs: **{repairs}**. Unresolved host links: **{unresolved_hosts}**.",
        "",
        "| BGB year | print-straive | print-pdf | vsmart | of which cross-listings | of which hosts |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for year in sorted(by_year, key=lambda value: (value is None, value or 0)):
        counts = by_year[year]
        label = "journals" if year is None else str(year)
        lines.append(
            f"| {label} | {counts['print-straive']} | {counts['print-pdf']} | {counts['vsmart']} "
            f"| {counts['cross-listing']} | {counts['host']} |"
        )
    lines.extend(["", "## Flags", ""])
    for name, count in flags.most_common(40):
        lines.append(f"- `{name}`: {count}")
    lines.extend(heading_report_lines(records))
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def heading_report_lines(records: list[Record]) -> list[str]:
    """One row per BGB year for the printed heading tree (plan B6)."""
    by_year: dict[int, list[Record]] = {}
    for record in records:
        if record.role != "entry" or record.bgb_year is None:
            continue
        by_year.setdefault(record.bgb_year, []).append(record)
    lines = [
        "",
        "## Headings",
        "",
        "Level-1 headings are the printed parts (Bibliographies, Généralités, Travaux généraux, "
        "Histoire par époques, and the Dutch titles). A roman numeral that is not one of those "
        "is listed in the last column.",
        "",
        "| BGB year | entries | distinct paths | max depth | depth > 6 | without period | level-1 outside the part list |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for year in sorted(by_year):
        group = by_year[year]
        total = len(group)
        paths = {tuple(record.section_path) for record in group if record.section_path}
        depths = [len(record.section_path) for record in group if record.section_path]
        deep = sum(1 for depth in depths if depth > 6)
        missing = sum(1 for record in group if not record.period)
        outside: dict[str, int] = {}
        for record in group:
            head = record.section_path[0] if record.section_path else ""
            if head and not is_part_heading(head):
                outside[head] = outside.get(head, 0) + 1
        outside_text = "; ".join(
            f"{text[:70]} ({count})" for text, count in sorted(outside.items(), key=lambda item: -item[1])
        )
        depth_share = f"{deep / total:.1%}" if total else "0"
        period_share = f"{missing / total:.1%}" if total else "0"
        lines.append(
            f"| {year} | {total} | {len(paths)} | {max(depths, default=0)} | {depth_share} "
            f"| {period_share} | {outside_text} |"
        )
    return lines


def heading_warnings(records: list[Record]) -> list[str]:
    """Years whose tree is still too deep, or whose top heading is not a known part."""
    by_year: dict[int, list[Record]] = {}
    for record in records:
        if record.role != "entry" or record.bgb_year is None or not record.section_path:
            continue
        by_year.setdefault(record.bgb_year, []).append(record)
    warnings: list[str] = []
    for year in sorted(by_year):
        group = by_year[year]
        deepest = max(len(record.section_path) for record in group)
        if deepest > 8:
            warnings.append(f"{year}: heading depth {deepest} is above 8")
        outside = sorted(
            {record.section_path[0] for record in group if not is_part_heading(record.section_path[0])}
        )
        for heading in outside:
            warnings.append(f"{year}: level-1 heading is not a part title: {heading[:90]}")
    return warnings


def _parent(code: str) -> str | None:
    body = code.rstrip(".")
    if "." not in body:
        return None
    return body.rsplit(".", 1)[0] + "."
