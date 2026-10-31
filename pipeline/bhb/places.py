"""Places from the printed place-name indexes (1990–2007).

Each volume of those years has a "Beknopte Index van Plaatsnamen / Index sommaire des noms de lieux": one paragraph
per place, followed by the print numbers of the entries about it, as "Aalst: 20592, 21161, 23203;". A sub-entry
("Land: 21107" for the Land van Aalst) follows on the next line after a semicolon, and "(Voir aussi - Zie ook: …)"
points to another spelling. The editors chose these places for what an entry is about, so they are checked values.
The files do not carry their year; it is the volume whose print numbers they match best.

Entries without an indexed place get the Belgian places their title names, marked as suggested (``title_places``).
The printed indexes set the rules: the editors index nearly every place a title names, also a place of birth, an
exhibition or an archive, so only a conference venue is skipped, and names that the indexed years show to be mostly
something else (Saint-Martin, Ligne, Belle …) are left out.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from bhb.textutil import squash

XML = etree.XMLParser(load_dtd=False, no_network=True, recover=True, resolve_entities=False, huge_tree=True)
_LINE = re.compile(r"^(?P<name>[^:]{1,120}?)\s*:\s*(?P<numbers>\d[\d,\s]*)(?P<rest>.*)$")
_SEE = re.compile(r"\(\s*(?:voir|zie)[^:]*:\s*(?P<other>[^)]+)\)", re.IGNORECASE)


@dataclass
class IndexLine:
    place: str
    detail: str | None
    numbers: list[str]
    see_also: list[str]


def index_paths(raw: Path) -> list[Path]:
    root = raw / "2023-12-29"
    return sorted({*root.glob("BGB_*/*Noms_de_Lieux*.xml"), *root.glob("BGB_*/*Plaatsnamen*.xml")})


def parse_index(path: Path) -> list[IndexLine]:
    lines: list[IndexLine] = []
    main: str | None = None
    previous_open = False
    for paragraph in etree.parse(str(path), XML).getroot().iter("p"):
        text = squash("".join(paragraph.itertext()))
        match = _LINE.match(text)
        if not match:
            previous_open = False
            continue
        name = match.group("name").strip(" .")
        numbers = re.findall(r"\d{3,6}", match.group("numbers"))
        see_also = [squash(item) for found in _SEE.finditer(match.group("rest")) for item in re.split(r",\s*", found.group("other"))]
        # A line right after one that ends in ";" is a sub-entry of that place ("Aalst: …;" then "Land: …").
        if previous_open and main:
            lines.append(IndexLine(main, name, numbers, see_also))
        else:
            main = name
            lines.append(IndexLine(name, None, numbers, see_also))
        previous_open = text.rstrip().endswith(";")
    return lines


def year_of_index(lines: list[IndexLine], numbers_by_year: dict[int, set[str]]) -> int | None:
    """The volume whose print numbers the index refers to; None when fewer than half of them match any volume."""
    wanted = {number for line in lines for number in line.numbers}
    if not wanted:
        return None
    year, overlap = max(((year, len(wanted & numbers)) for year, numbers in numbers_by_year.items()), key=lambda item: item[1])
    return year if overlap >= len(wanted) / 2 else None


def places_from_indexes(raw: Path, numbers_by_year: dict[int, set[str]]) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Record id → places, and per-file statistics. A sub-entry counts for its main place (the Land van Aalst under
    Aalst), since the facet works at the level of the place the editors indexed."""
    found: dict[str, list[str]] = defaultdict(list)
    stats: Counter[str] = Counter()
    for path in index_paths(raw):
        lines = parse_index(path)
        year = year_of_index(lines, numbers_by_year)
        stats["files"] += 1
        if year is None:
            stats["files without a year"] += 1
            continue
        for line in lines:
            for number in line.numbers:
                if number not in numbers_by_year[year]:
                    stats["numbers not found"] += 1
                    continue
                record_id = f"bhb:{year}-{number}"
                if line.place not in found[record_id]:
                    found[record_id].append(line.place)
                stats["links"] += 1
    return dict(found), dict(stats)


LEVELS = ("municipality", "area", "section")
# Names shared by a municipality and a province mean the city (Antwerpen, Liège, Namur), with one exception: the
# Dutch "Limburg" in a Belgian history index is the province, not the town of Limbourg near Verviers (whose
# French name, like the old Duchy of Limbourg around it, stays with the town).
OVERRIDES = {"limburg": "70000"}
# Names that, unqualified, mean a place abroad: Lille is the French city far more often than the village near
# Turnhout, which the indexes write "Lille (België)" or "Lille (Kempen)".
ABROAD = {"lille"}
# A qualifier in parentheses that puts the place abroad ("Lille (France)") keeps the name as printed.
FOREIGN = {
    "france", "frankrijk", "frankreich", "nederland", "pays bas", "niederlande", "duitsland", "allemagne",
    "deutschland", "engeland", "angleterre", "england", "italie", "italia", "espagne", "spanje",
}


def gazetteer_path() -> Path:
    from bhb.paths import repo_root

    return repo_root() / "data" / "curated" / "gazetteer.csv"


def load_gazetteer(path: Path | None = None) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    """Rows by NIS code, and every folded label (French, Dutch, German, English) → NIS codes."""
    import csv

    from bhb.textutil import fold

    rows: dict[str, dict[str, str]] = {}
    labels: dict[str, list[str]] = defaultdict(list)
    with (path or gazetteer_path()).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows[row["nis"]] = row
            for language in ("fr", "nl", "de", "en"):
                for label in (row.get(f"label_{language}") or "").split("/"):
                    if label.strip() and row["nis"] not in labels[fold(label)]:
                        labels[fold(label)].append(row["nis"])
    return rows, dict(labels)


def resolve(name: str, rows: dict[str, dict[str, str]], labels: dict[str, list[str]]) -> str | None:
    """The NIS code of a printed place name: a municipality before an area (province, region) before a section;
    None when the name is unknown or two places of the same level share it."""
    from bhb.textutil import fold

    qualifiers = [fold(text) for text in re.findall(r"\(([^)]*)\)", name)]
    if any(qualifier in FOREIGN for qualifier in qualifiers):
        return None
    key = fold(re.sub(r"\s*\(.*?\)\s*", " ", name))
    if key in ABROAD and not qualifiers:
        return None
    if key in OVERRIDES and OVERRIDES[key] in rows:
        return OVERRIDES[key]
    found = labels.get(key, [])
    for level in LEVELS:
        codes = sorted(code for code in found if rows[code]["level"] == level)
        if len(codes) == 1 or (len(codes) > 1 and _same_place(codes, rows)):
            return codes[0]
        if len(codes) > 1:
            return None
    return None


def _same_place(codes: list[str], rows: dict[str, dict[str, str]]) -> bool:
    """Two codes for one place, such as a municipality before and after a merger, lie within a few kilometres."""
    points = [(float(rows[code]["lon"]), float(rows[code]["lat"])) for code in codes if rows[code].get("lon") and rows[code].get("lat")]
    return len(points) == len(codes) and all(abs(lon - points[0][0]) < 0.08 and abs(lat - points[0][1]) < 0.05 for lon, lat in points)


def apply_places(records, raw: Path) -> dict[str, int]:
    """Give every entry the places its volume's printed index lists: ``place_ids`` holds the NIS code
    (``nis:44021``) or, for a region or place abroad not in the gazetteer, the printed name (``name:Wallonie``);
    ``places`` holds readable names. The places are the editors', so they are not marked as suggested. Entries
    without one then get the places their title names, in ``place_suggested`` too."""
    rows, labels = load_gazetteer()
    numbers_by_year: dict[int, set[str]] = defaultdict(set)
    for record in records:
        if record.print_number and record.bgb_year and record.id == f"bhb:{record.bgb_year}-{record.print_number}":
            numbers_by_year[record.bgb_year].add(record.print_number)
    found, stats = places_from_indexes(raw, numbers_by_year)
    by_id = {record.id: record for record in records}
    counts: Counter[str] = Counter(stats)
    for record in records:
        record.place_ids, record.places, record.place_suggested = [], [], []
    for record_id, names in found.items():
        record = by_id.get(record_id)
        if record is None:
            continue
        ids: list[str] = []
        readable: list[str] = []
        for name in names:
            code = resolve(name, rows, labels)
            key = f"nis:{code}" if code else f"name:{name}"
            if key in ids:
                continue
            ids.append(key)
            readable.append((rows[code]["label_nl"] or rows[code]["label_fr"]) if code else name)
            counts["resolved" if code else "kept as printed"] += 1
        record.place_ids = ids
        record.places = readable
        counts["entries"] += 1
    counts.update(title_places(records, rows, labels))
    return dict(counts)


# A place is left out when the words before it in its clause name a conference and the place is its venue
# ("Colloque international, Gand, 27–30 avril", "congres gehouden te Gent"): the meeting place, not the subject.
_CONFERENCE = re.compile(
    r"\b(colloques?|colloqui(um|a)|congres|congress|kongress|congresso|symposium|journees? d etudes?|studiedag(en)?"
    r"|conferences?|conferentie|workshop|tenue?s?|gehouden|held)\b"
)
_TOKEN = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
_SAINT = re.compile(r"^(saint|sainte|sint|sankt) ")
# Names that the indexed years show to be mostly something else: at least this many title matches, with fewer than
# this share of them in the printed index of the same entry.
STOP_MIN_MATCHES = 3
STOP_AGREEMENT = 0.6


@dataclass
class TitleMatcher:
    """Finds gazetteer names in a title: municipalities and sections only, since a province or region of the same
    name is often a historical territory (the county of Flanders, the duchy of Brabant, Luxembourg), and only where
    the name starts with a capital."""

    codes: dict[str, str]
    stop: frozenset[str] = frozenset()

    @classmethod
    def from_gazetteer(cls, rows: dict[str, dict[str, str]], labels: dict[str, list[str]]) -> "TitleMatcher":
        codes = {}
        for key in labels:
            code = resolve(key, rows, labels)
            if not code or rows[code]["level"] == "area":
                continue
            # Sections named after a saint are mostly a church or the saint (Saint-Martin, Sint-Jan).
            if rows[code]["level"] == "section" and _SAINT.match(key):
                continue
            codes[key] = code
        return cls(codes)

    def find(self, text: str) -> list[tuple[str, str]]:
        """(folded name, NIS code) for each place the text names, longest name first, without conference venues."""
        from bhb.textutil import fold

        tokens = [(match.group(), match.start(), match.end()) for match in _TOKEN.finditer(text)]
        folded = [fold(token) for token, _, _ in tokens]
        longest = 6
        found: list[tuple[str, str]] = []
        index = 0
        while index < len(tokens):
            for size in range(min(longest, len(tokens) - index), 0, -1):
                key = " ".join(folded[index:index + size])
                if key in self.codes and key not in self.stop and tokens[index][0][:1].isupper():
                    start, end = tokens[index][1], tokens[index + size - 1][2]
                    if not _is_venue(text, start, end) and not _is_other(text, start, end) and (key, self.codes[key]) not in found:
                        found.append((key, self.codes[key]))
                    index += size
                    break
            else:
                index += 1
        return found


# A German article or conjunction before a capitalised word makes it a German noun ("Völker, Reiche und Namen",
# "das Essen"), and "Bergen op Zoom" is in the Netherlands, not Mons.
_GERMAN_BEFORE = re.compile(r"\b(und|der|die|das|den|dem|des|ihre|seine|mit|ohne|zum|zur)\s+$")


def _is_other(text: str, start: int, end: int) -> bool:
    return bool(_GERMAN_BEFORE.search(text[max(0, start - 8):start]) or re.match(r"[\s-]+op[\s-]+Zoom", text[end:end + 9]))


def _is_venue(text: str, start: int, end: int) -> bool:
    from bhb.textutil import fold

    clauses = re.split(r"[.;:\[\]]|\s[-–]\s", text[:start])
    after = text[end:end + 6]
    # A place that is a clause of its own, right after the conference ("Colloque international. Spa.").
    if not clauses[-1].strip() and len(clauses) > 1 and _CONFERENCE.search(fold(clauses[-2])):
        return bool(re.match(r"\s*([.,;)]|$)", after))
    if not _CONFERENCE.search(fold(clauses[-1])):
        return False
    return bool(re.match(r"\s*,?\s*\d", after) or re.search(r"\b(te|à|a|in|at|en)\s*$", text[:start]))


def _title(record) -> str:
    return " ".join(part for part in (record.title, record.subtitle) if part)


def _agrees(record, key: str, code: str, labels_of: dict[str, set[str]]) -> bool:
    """Whether a place found in the title is in the entry's printed index, as a code or as a printed name that
    starts with one of its labels ("Luik, prinsbisdom" for Liège)."""
    from bhb.textutil import fold

    return f"nis:{code}" in record.place_ids or any(fold(name).startswith(label) for name in record.places for label in labels_of[code])


def title_places(records, rows: dict[str, dict[str, str]], labels: dict[str, list[str]]) -> dict[str, int]:
    """Suggest places from the title for entries without an indexed place; tune the stop list on the entries with
    one. Returns statistics, including the agreement of the kept names with the printed index."""
    matcher = TitleMatcher.from_gazetteer(rows, labels)
    labels_of: dict[str, set[str]] = defaultdict(set)
    for key, code in matcher.codes.items():
        labels_of[code].add(key)
    tally: dict[str, Counter[bool]] = defaultdict(Counter)
    indexed = [record for record in records if record.place_ids]
    for record in indexed:
        for key, code in matcher.find(_title(record)):
            tally[key][_agrees(record, key, code, labels_of)] += 1
    matcher.stop = frozenset(
        key for key, count in tally.items()
        if sum(count.values()) >= STOP_MIN_MATCHES and count[True] / sum(count.values()) < STOP_AGREEMENT
    )
    agree = sum(count[True] for key, count in tally.items() if key not in matcher.stop)
    checked = sum(sum(count.values()) for key, count in tally.items() if key not in matcher.stop)
    counts: Counter[str] = Counter({"title names left out": len(matcher.stop), "title agreement (per mille)": round(1000 * agree / max(1, checked))})
    for record in records:
        if record.place_ids or record.role != "entry":
            continue
        found = matcher.find(_title(record))
        if not found:
            continue
        record.place_ids = [f"nis:{code}" for _, code in found]
        record.places = [rows[code]["label_nl"] or rows[code]["label_fr"] for _, code in found]
        record.place_suggested = list(record.place_ids)
        counts["entries with title places"] += 1
        counts["title places"] += len(found)
    return dict(counts)
