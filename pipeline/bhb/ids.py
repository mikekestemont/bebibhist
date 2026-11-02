"""Ids that last (plan §4d, step 1): an entry whose id changes keeps its former ids, so old links still find it.

A printed entry's id holds its printed number, and a repaired number changes it. The entry itself is the same
element of the same delivered file, so the previous build is matched on (file, element id, part): the part is the
``-c3`` of a contribution split from its volume, or the ``-dup2`` of a repeated number.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_PART = re.compile(r"-(c\d+|dup\d+)$")


def _key(record_id: str, provenance: dict) -> tuple[str, str, str] | None:
    file, element = provenance.get("file"), provenance.get("xml_id")
    if not file or not element:
        return None
    part = _PART.search(record_id)
    return Path(file).name, element, part.group(1) if part else ""


def previous_ids(path: Path) -> dict[tuple[str, str, str], list[str]]:
    """For each entry of an earlier build: its id and former ids, by key."""
    found: dict[tuple[str, str, str], list[str]] = {}
    if not path.is_file():
        return found
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            data = json.loads(line)
            key = _key(data["id"], data.get("provenance") or {})
            if key is not None:
                found[key] = [data["id"], *(data.get("former_ids") or [])]
    return found


def carry_former_ids(records, earlier: dict[tuple[str, str, str], list[str]]) -> dict[str, str]:
    """Give every record the ids it had before, other than its own; returns previous id → new id for the records
    whose id changed in this build."""
    changed: dict[str, str] = {}
    for record in records:
        key = _key(record.id, {"file": record.provenance.file, "xml_id": record.provenance.xml_id})
        before = earlier.get(key) if key else None
        if not before:
            continue
        record.former_ids = [old for old in dict.fromkeys(before) if old != record.id]
        if before[0] != record.id:
            changed[before[0]] = record.id
    return changed


_ID = re.compile(r"bhb:(?:vs-)?[0-9][\w-]*")
# Files that store matches or hand checks by record id: they follow a renumbering, or they would attach a DOI, an
# ISBN or a checked label to whichever entry now holds the old id.
ID_FILES = ("build/identifiers/*.csv", "build/identifiers/*.json", "build/candidates/*.csv",
            "data/curated/corrections.csv", "data/curated/language/*.csv", "data/curated/gold/*.xlsx")


def migrate_ids(root: Path, mapping: dict[str, str]) -> dict[str, int]:
    """Rewrite every id in the files of ``ID_FILES`` from its previous to its new form, all at once (an old id may
    be another entry's new one). Returns the replacements per file."""
    counts: dict[str, int] = {}
    if not mapping:
        return counts
    for pattern in ID_FILES:
        for path in sorted(root.glob(pattern)):
            if path.suffix == ".xlsx":
                if hits := _migrate_workbook(path, mapping):
                    counts[str(path.relative_to(root))] = hits
                continue
            with path.open(encoding="utf-8", newline="") as handle:
                text = handle.read()
            hits = 0

            def swap(match: re.Match[str]) -> str:
                nonlocal hits
                new = mapping.get(match.group())
                if new is None:
                    return match.group()
                hits += 1
                return new

            moved = _ID.sub(swap, text)
            if hits:
                with path.open("w", encoding="utf-8", newline="") as handle:
                    handle.write(moved)
                counts[str(path.relative_to(root))] = hits
    return counts


def _migrate_workbook(path: Path, mapping: dict[str, str]) -> int:
    """The same for a spreadsheet to check by hand: only cells that hold an id and nothing else."""
    import openpyxl

    workbook = openpyxl.load_workbook(path)
    hits = 0
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value in mapping:
                    cell.value = mapping[cell.value]
                    hits += 1
    if hits:
        workbook.save(path)
    return hits
