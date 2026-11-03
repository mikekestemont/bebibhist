"""Hand corrections (`data/curated/corrections.csv`), applied right after ingest, before anything reads the text.

One row per correction: the entry, the text as it reached us, the text as it should read, the kind, and who checked
it against the printed volume, when. Two kinds:

- ``ocr``: the digitisation misread the volume ("Zuznkir" for Zumkir). The text is corrected everywhere the entry holds
  it, the printed citation included, since the volume itself has the right form.
- ``print``: the volume itself is wrong. The printed citation stays as printed; only the parsed fields (title, name,
  year) are corrected.

The row keeps the wrong reading, and the raw files are never changed, so nothing is lost. A row whose wrong text the
entry no longer holds (a new delivery fixed it, or the id changed) is reported, not applied.
"""

from __future__ import annotations

import csv
import dataclasses
import re
import sys
from pathlib import Path

from bhb.paths import repo_root

KINDS = ("ocr", "print")
# Fields that are identifiers or links, not text: never rewritten.
_SKIP = {"id", "provenance", "similar", "similar_scores", "place_ids", "place_suggested", "bhb_codes", "categories",
         "orcid", "orcid_from", "kbr_id", "name_from", "journal_id"}


def corrections_path() -> Path:
    return repo_root() / "data" / "curated" / "corrections.csv"


def machine_corrections_path() -> Path:
    """OCR corrections found by comparing two digitisations (``bhb corrections persee``), not checked by a person."""
    return repo_root() / "data" / "curated" / "ocr_persee.csv"


def load_corrections(path: Path | None = None) -> list[dict[str, str]]:
    """The hand corrections, then the machine-found ones; or the rows of one file."""
    if path is None:
        return load_corrections(corrections_path()) + load_corrections(machine_corrections_path())
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if (row.get("id") or "").strip()]
    for row in rows:
        if row["kind"] not in KINDS or not row["wrong"] or row["wrong"] == row["right"]:
            raise ValueError(f"corrections.csv: bad row for {row['id']}: kind must be one of {KINDS}, wrong set and not equal to right")
    return rows


def _replace(value, wrong: str, right: str):
    """The value with ``wrong`` replaced in every text field, and whether anything changed. A wrong text that begins
    and ends with a letter is replaced as a whole word only: "el" → "et" leaves "Michel" alone."""
    if isinstance(value, str):
        if re.match(r"\w", wrong) and re.search(r"\w$", wrong):
            new, count = re.subn(rf"(?<!\w){re.escape(wrong)}(?!\w)", lambda _: right, value)
            return new, count > 0
        return (value.replace(wrong, right), True) if wrong in value else (value, False)
    if isinstance(value, list):
        changed = False
        for index, item in enumerate(value):
            value[index], hit = _replace(item, wrong, right)
            changed |= hit
        return value, changed
    if dataclasses.is_dataclass(value):
        changed = False
        for item in dataclasses.fields(value):
            if item.name in _SKIP:
                continue
            new, hit = _replace(getattr(value, item.name), wrong, right)
            if hit:
                setattr(value, item.name, new)
                changed = True
        return value, changed
    return value, False


def apply_corrections(records, rows: list[dict[str, str]] | None = None) -> int:
    """Apply the corrections to the records in place; returns how many rows were applied. A machine-found row
    (``checked_by`` "machine: …") flags the entry ``corrected-ocr-machine``, so it shows as machine-derived."""
    rows = load_corrections() if rows is None else rows
    by_id = {record.id: record for record in records}
    applied = 0
    for row in rows:
        record = by_id.get(row["id"])
        if record is None:
            print(f"correction not applied, no entry {row['id']}: {row['wrong']} → {row['right']}", file=sys.stderr)
            continue
        # A printer's error stays in the printed citation: hide it while the parsed fields are corrected.
        printed = record.printed
        if row["kind"] == "print":
            record.printed = None
        _, changed = _replace(record, row["wrong"], row["right"])
        if row["kind"] == "print":
            record.printed = printed
        if not changed:
            print(f"correction not applied, {row['id']} no longer holds {row['wrong']!r}", file=sys.stderr)
            continue
        machine = (row.get("checked_by") or "").startswith("machine")
        record.provenance.flags.append(f"corrected-{row['kind']}" + ("-machine" if machine else ""))
        applied += 1
    return applied
