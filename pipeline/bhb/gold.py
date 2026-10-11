"""Gold-standard sample and field-level scores.

Until a human corrects ``data/curated/gold/gold.xlsx``, scoring uses the 40
entries the 2026 interns corrected (20 books and 20 others, all from BGB 1992).
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook, load_workbook

from bhb.model import Record
from bhb.paths import raw_root, repo_root
from bhb.textutil import squash

SAMPLE_COLUMNS = (
    "id",
    "printed",
    "type",
    "title",
    "persons",
    "host_title",
    "volume",
    "issue",
    "year",
    "pages",
    "publisher_place",
    "publisher_name",
    "note",
    "theme",
)

SMOKE_FILES = (
    "legacy/stage-2026/Notebooks/Other_Gold_Standard /final_test_sample_1992_corrected.xlsx",
    "legacy/stage-2026/Notebooks/Other_Gold_Standard /sample_other_1992_corrected.xlsx",
)

# Fields the prototype may use as facets only when they clear these rates.
TARGETS = {"title": 0.90, "surname": 0.95, "year": 0.95, "host": 0.85}


@dataclass
class GoldRow:
    label: str
    bgb_year: int
    title: str
    host_title: str
    surname: str
    year: str
    kind: str


@dataclass
class Score:
    compared: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    correct: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    missing_records: int = 0
    rows: int = 0

    def add(self, field_name: str, ok: bool) -> None:
        self.compared[field_name] += 1
        if ok:
            self.correct[field_name] += 1

    def rate(self, field_name: str) -> float | None:
        total = self.compared[field_name]
        if not total:
            return None
        return self.correct[field_name] / total


def write_sample(records: list[Record], path: Path, n: int = 300, seed: int = 2026) -> int:
    """Stratified random print entries, pre-filled with the parser output.

    The 300-entry sheet also carries 100 further pre-1993 rows, with an empty
    ``theme`` column, so that pass can check the classifier on the older schemes.
    """
    chosen = stratified_sample(records, n, seed)
    extra = extra_pre1993(records, chosen, 100, seed) if n >= 300 else []
    book = Workbook()
    sheet = book.active
    sheet.title = "gold"
    sheet.append(list(SAMPLE_COLUMNS))
    for record in [*chosen, *extra]:
        sheet.append([_cell(record, column) for column in SAMPLE_COLUMNS])
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    return len(chosen) + len(extra)


def stratified_sample(records: list[Record], n: int, seed: int) -> list[Record]:
    pool = [
        record
        for record in records
        if record.source.startswith("print") and record.role == "entry" and not record.is_cross_listing
    ]
    by_decade: dict[int, list[Record]] = defaultdict(list)
    for record in pool:
        if record.bgb_year:
            by_decade[(record.bgb_year // 10) * 10].append(record)
    decades = sorted(by_decade)
    if not decades:
        return []
    rng = random.Random(seed)
    base, extra = divmod(n, len(decades))
    chosen: list[Record] = []
    for index, decade in enumerate(decades):
        want = base + (1 if index < extra else 0)
        group = by_decade[decade]
        rng.shuffle(group)
        chosen.extend(group[:want])
    chosen.sort(key=lambda record: (record.bgb_year or 0, record.print_number or ""))
    return chosen


def extra_pre1993(records: list[Record], chosen: list[Record], n: int, seed: int) -> list[Record]:
    """Pre-1993 print entries that the stratified draw did not already take."""
    taken = {record.id for record in chosen}
    pool = [
        record
        for record in records
        if record.source.startswith("print")
        and record.role == "entry"
        and not record.is_cross_listing
        and record.bgb_year
        and record.bgb_year < 1993
        and record.id not in taken
    ]
    rng = random.Random(seed)
    rng.shuffle(pool)
    extra = pool[:n]
    extra.sort(key=lambda record: (record.bgb_year or 0, record.print_number or ""))
    return extra


def load_gold(paths: list[Path] | None = None) -> list[GoldRow]:
    files = paths or _default_gold_files()
    rows: list[GoldRow] = []
    for path in files:
        rows.extend(_read_sheet(path))
    return rows


def score_records(records: list[Record], gold: list[GoldRow]) -> Score:
    index = {
        (record.bgb_year, record.print_number): record
        for record in records
        if record.print_number
    }
    score = Score(rows=len(gold))
    for row in gold:
        record = index.get((row.bgb_year, row.label))
        if record is None:
            score.missing_records += 1
            continue
        if row.title:
            score.add("title", _same(row.title, record.title))
        if row.surname:
            family = record.persons[0].family if record.persons else ""
            score.add("surname", _same(row.surname, family))
        if row.year:
            score.add("year", str(record.year or "") == row.year)
        if row.host_title:
            host = record.host.title if record.host else ""
            score.add("host", _same(row.host_title, host))
    return score


def format_score(score: Score) -> str:
    lines = [
        f"Gold rows: {score.rows}. Records not found: {score.missing_records}.",
        "",
        "| Field | Compared | Correct | Accuracy | Target |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in ("title", "surname", "year", "host"):
        total = score.compared[name]
        rate = score.rate(name)
        shown = "—" if rate is None else f"{rate:.0%}"
        target = f"{TARGETS[name]:.0%}"
        lines.append(f"| {name} | {total} | {score.correct[name]} | {shown} | {target} |")
    lines.append("")
    return "\n".join(lines)


def _default_gold_files() -> list[Path]:
    root = repo_root()
    curated = root / "data" / "curated" / "gold" / "gold.xlsx"
    if curated.is_file():
        return [curated]
    return [raw_root() / relative for relative in SMOKE_FILES]


def _read_sheet(path: Path) -> list[GoldRow]:
    book = load_workbook(path, read_only=True, data_only=True)
    sheet = book.active
    rows = sheet.iter_rows(values_only=True)
    header = [str(cell).strip() if cell is not None else "" for cell in next(rows)]
    index = {name: position for position, name in enumerate(header)}
    found: list[GoldRow] = []
    for values in rows:
        label = _at(values, index, "label")
        if label.endswith(".0"):
            label = label[:-2]
        if "person_1" in index:
            article = _at(values, index, "article_title") or _at(values, index, "chapter_title")
            title = _at(values, index, "title")
            work_title = article or title
            host = title if article else ""
            person = _at(values, index, "person_1")
            surname = person.split(",")[0].strip() if person else ""
            kind = _at(values, index, "publication_type")
            bgb_year = _year_of(path, values, index)
        else:
            work_title = _at(values, index, "title")
            host = _at(values, index, "host_title")
            person = _at(values, index, "persons").split(";")[0]
            surname = person.split(",")[0].strip() if person else ""
            kind = _at(values, index, "type")
            bgb_year = _year_from_id(_at(values, index, "id")) or _year_of(path, values, index)
            if not label:
                label = _label_from_id(_at(values, index, "id"))
        year = _at(values, index, "year")
        if year.endswith(".0"):
            year = year[:-2]
        if not label:
            continue
        found.append(
            GoldRow(
                label=label,
                bgb_year=bgb_year,
                title=work_title,
                host_title=host,
                surname=surname,
                year=year,
                kind=kind,
            )
        )
    book.close()
    return found


def _year_from_id(record_id: str) -> int | None:
    match = re.search(r"bhb:(\d{4})-", record_id)
    return int(match.group(1)) if match else None


def _label_from_id(record_id: str) -> str:
    match = re.search(r"bhb:\d{4}-(.+)$", record_id)
    return match.group(1) if match else ""


def _year_of(path: Path, values: tuple, index: dict[str, int]) -> int:
    """Intern sheets are BGB 1992. A curated file may carry ``bgb_year``."""
    raw = _at(values, index, "bgb_year")
    if raw.isdigit():
        return int(raw)
    if "1992" in path.name:
        return 1992
    return 1992


def _at(values: tuple, index: dict[str, int], name: str) -> str:
    position = index.get(name)
    if position is None or position >= len(values) or values[position] is None:
        return ""
    return squash(str(values[position]))


def _same(left: str, right: str | None) -> bool:
    return _norm(left) == _norm(right or "")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = squash(text).casefold().strip(" .…,")
    return text


def _cell(record: Record, column: str) -> str:
    persons = "; ".join(
        f"{person.family}, {person.given}" if person.given else person.family for person in record.persons
    )
    values = {
        "id": record.id,
        "printed": record.printed or "",
        "type": record.type,
        "title": record.title or "",
        "persons": persons,
        "host_title": record.host.title if record.host and record.host.title else "",
        "volume": record.host.volume if record.host and record.host.volume else "",
        "issue": record.host.issue if record.host and record.host.issue else "",
        "year": "" if record.year is None else str(record.year),
        "pages": (record.host.pages if record.host and record.host.pages else "") or (record.extent or ""),
        "publisher_place": record.publisher.place if record.publisher and record.publisher.place else "",
        "publisher_name": record.publisher.name if record.publisher and record.publisher.name else "",
        "note": record.note or "",
        "theme": "",
    }
    return values[column]
