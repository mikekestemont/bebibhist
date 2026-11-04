"""The Belgian Bibliography of KBR (legal deposit): ISBNs, links and authors' full names (`docs/IMPLEMENTATION_PLAN.md`
§4e).

KBR offers the set ``BelgianDataset`` (about 1.1 million records, Dublin Core) at ``opac.kbr.be/oaiserver.ashx``
(https://opac.kbr.be/belgian-bibliography.aspx). It is harvested by date windows (``bhb.kbr_harvest``), page by page,
gzipped, into ``build/external/kbr/``.

The books of the bibliography, and the collected volumes of its chapters, are matched to it on the ISBN or on the
title with an author or the publisher (``match``); for each match the richer ``ermes`` record gives the year and the
authors' KBR authority ids (``ermes``). ``apply_kbr`` writes the ISBN, the KBR link and, where the entry prints
initials only, the author's name as KBR writes it out, on the matched book and, when the name can only be that
person, on the author's other entries. All of it is machine-derived and labelled; the printed citation is untouched.
"""

from __future__ import annotations

import csv
import gzip
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from bhb.identifiers import USER_AGENT, _full_given, numbers_agree, same_name
from bhb.kbr_harvest import _RECORD, OAI
from rapidfuzz.distance import Levenshtein

from bhb.textutil import fold, squash

INTERVAL = 1.0
# Belgian publishers print ISBNs from the early 1970s; before that a record with one is a later reprint.
ISBN_FROM = 1972


_ISBN_FIELD = re.compile(r"<dc:identifier>(?:97[89])?\d{9}[\dXx]</dc:identifier>")


# --- The harvested records ------------------------------------------------------------------------------------------

_FIELD = re.compile(r"<dc:(\w+)[^>]*>(.*?)</dc:\1>", re.S)
_SHELF_YEAR = re.compile(r"<callnumber>[^<]*?\b(1[89]\d\d|20[0-4]\d)\b")


@dataclass
class Book:
    number: str  # KBR's record number: https://uurl.kbr.be/bib/<number>
    title: str  # without the statement of responsibility
    creators: list[str] = field(default_factory=list)
    publishers: list[str] = field(default_factory=list)
    isbn: list[str] = field(default_factory=list)
    # The year in the legal-deposit shelf mark ("BB A 2009 1.353"): the year of deposit, the year of publication or
    # shortly after. The record itself has no date in Dublin Core.
    shelf_year: int | None = None


def _isbn(value: str) -> str | None:
    digits = re.sub(r"[^0-9Xx]", "", value)
    return digits.upper() if len(digits) in (10, 13) and re.fullmatch(r"[0-9Xx][0-9Xx -]+", value.strip()) else None


def parse_record(record: str) -> Book | None:
    """A harvested record as a ``Book``; None for a periodical or a record without number or title."""
    fields: dict[str, list[str]] = {}
    for tag, value in _FIELD.findall(record):
        fields.setdefault(tag, []).append(html.unescape(value).strip())
    if (fields.get("type") or [""])[0] != "Livre":
        return None
    number = next((value.rsplit("/", 1)[1] for value in fields.get("identifier", []) if value.startswith("https://uurl.kbr.be/bib/")), "")
    title = squash((fields.get("title") or [""])[0].split(" / ")[0])
    if not number or not title:
        return None
    isbn = []
    for value in fields.get("identifier", []):
        if (found := _isbn(value)) and found not in isbn:
            isbn.append(found)
    shelf = _SHELF_YEAR.search(record)
    return Book(number, title, fields.get("creator", []), fields.get("publisher", []), isbn, int(shelf.group(1)) if shelf else None)


def books(folder: Path):
    """Every harvested book, once: a record that changed during the harvest is found again in a later window, and the
    later page is read first."""
    seen: set[str] = set()
    for path in sorted(folder.glob("page-*.xml.gz"), reverse=True):
        for record in _RECORD.findall(gzip.decompress(path.read_bytes()).decode("utf-8")):
            if (book := parse_record(record)) is not None and book.number not in seen:
                seen.add(book.number)
                yield book


# --- Names as KBR writes them ---------------------------------------------------------------------------------------

@dataclass
class Name:
    family: str
    given: str = ""
    born: int | None = None
    died: int | None = None
    kbr_id: str | None = None

    @property
    def dates(self) -> str | None:
        return f"{self.born or ''}-{self.died or ''}" if self.born or self.died else None


# KBR follows a name with its role ("Auteur", "Traducteur", "Directeur de la publication", "Publisher", ...).
_ROLE = re.compile(r"\.\s*(?:Auteur|Author|Publisher|Illustrat|Tradu|Translat|Directeur|Publishing|Photograph|Sc[ée]nariste|"
                   r"Propriétaire|Graphiste|Compil|R[ée]dact|Redakt|Colorist|D'après|Contribut|Adaptat|Imprimeur|Printer|"
                   r"Organisat|Concepteur|Editor|[ÉE]diteur|Cr[ée]ateur|Typographe|Cartographe|Chorégraphe|Danseur|Herausgeber|"
                   r"Hrsg|Uitgever|Vertaler|Musicien|Composit|Pr[ée]fac|Dessinat|Coordinat|Autre|Other|Annotat|Commentat|"
                   r"Interprète|Narrat|Calligraph|Relieur|Former owner|Sponsor|Dédica|Honoré)[^()]*$")
_DATES = re.compile(r"\((?:fl\.\s*|ca\.?\s*)?(\d{4})?\??\s*-\s*(?:ca\.?\s*)?(\d{4})?\??\)")


def parse_name(text: str, kbr_id: str | None = None) -> Name | None:
    """A person as KBR writes one ("Duquet, Frans (1922-2013) - heemkundige. Auteur"); None for a body ("Dupuis
    (Marcinelle). Publisher") or a name without given name."""
    text = squash(text).replace(" .", ".")
    born = died = None
    if dates := _DATES.search(text):
        born, died = (int(value) if value else None for value in dates.groups())
        text = text[:dates.start()]
    text = text.split(" - ")[0]
    while (role := _ROLE.search(text)) and role.start() > text.find(","):
        text = text[:role.start()]
    family, comma, given = text.partition(",")
    if not comma or not given.strip() or "(" in family:
        return None
    return Name(family.strip(), given.strip(" ,"), born, died, kbr_id)


def _parts(given: str) -> list[str]:
    return [part for part in re.split(r"[\s.\-]+", fold(given or "")) if part]


def name_fits(ours: str | None, theirs: str) -> bool:
    """The given name of the entry ("W.", "M.-A.", "Jul.", empty) fits the one KBR writes out: each part is the
    start of the matching part, and an initial I and J are one (the OCR confuses them)."""
    left, right = _parts(ours or ""), _parts(theirs)
    if len(left) > len(right):
        return False
    for part, full in zip(left, right):
        if not (full.startswith(part) or (len(part) == 1 and {part, full[0]} <= {"i", "j"})):
            return False
    return True


def written_out(given: str | None) -> bool:
    """A given name written out ("Walter", "Jo", "Marie-Christine"), not initials or a contraction ("W.", "Th",
    "Jul.")."""
    return bool(_full_given(given)) and all(re.search(r"[aeiouy]", part) for part in _parts(given))


# --- Matching -------------------------------------------------------------------------------------------------------

def _keys(title: str) -> tuple[str, str]:
    """The folded title, and its main part (before a subtitle) when it has three words or more."""
    whole = fold(title)
    main = fold(re.split(r"\s+[:;]\s+|\.\s+(?=[A-ZÀ-Ý])", title, maxsplit=1)[0])
    return whole, (main if main != whole and len(main.split()) >= 3 else "")


@dataclass
class Target:
    """A book of the bibliography, or a collected volume of its chapters, to look up in KBR."""
    key: str
    title: str
    year: int | None
    families: list[str]
    publisher: str
    isbn: list[str]
    chapters: list[str] = field(default_factory=list)


def targets(records) -> list[Target]:
    from bhb.openlibrary import hosts

    found = []
    for record in records:
        if record.role == "entry" and record.type == "book" and record.title:
            title = ": ".join(part for part in (record.title, record.subtitle) if part)
            found.append(Target(record.id, title, record.year, [person.family for person in record.persons],
                                (record.publisher.name if record.publisher else "") or "", list(record.isbn)))
    for key, (volume, chapters) in hosts(records, since=None).items():
        title = ": ".join(part for part in (volume.title, volume.subtitle) if part)
        found.append(Target(f"volume:{key}", title, volume.year, [person.family for person in volume.persons],
                            (volume.publisher.name if volume.publisher else "") or "", [], chapters))
    return found


@dataclass
class KbrMatch:
    key: str
    chapters: list[str]
    number: str
    isbn: list[str]
    basis: str  # "isbn", "author" or "publisher"
    shelf_year: int | None
    year: int | None
    ours: str
    theirs: str
    creators: list[str]


def _words(text: str) -> set[str]:
    return {word for word in fold(text).split() if len(word) >= 4}


def _check(target: Target, book: Book, whole: bool) -> str | None:
    """Why the KBR book is the target ("author" or "publisher"), or None."""
    if numbers_agree(target.title, book.title) is False:
        return None
    if target.isbn and book.isbn and not set(target.isbn) & set(book.isbn):
        return None  # another edition
    if target.year and book.shelf_year and not -1 <= book.shelf_year - target.year <= 3:
        return None
    theirs = [name.split(",")[0] for name in book.creators]
    if any(same_name(ours, family) for ours in target.families if ours for family in theirs):
        return "author"
    publisher = _words(target.publisher) & _words(" ".join(book.publishers))
    if whole and publisher and target.year and book.shelf_year in (target.year, target.year + 1) and len(fold(target.title).split()) >= 3:
        return "publisher"
    return None


def match(records, books_found) -> tuple[list[KbrMatch], dict[str, int]]:
    """Match the bibliography's books and volumes to KBR's books. One pass over the harvest: only the books whose
    title or ISBN some target has are kept. A target with several KBR books that fit and different ISBNs is left
    out (editions, volumes), unless only one of them has an ISBN, the target is of the ISBN era and the years agree:
    then KBR holds one book more than once."""
    from collections import Counter, defaultdict

    wanted = targets(records)
    by_title: dict[str, list[tuple[Target, bool]]] = defaultdict(list)
    by_isbn: dict[str, list[Target]] = defaultdict(list)
    for target in wanted:
        whole, main = _keys(target.title)
        by_title[whole].append((target, True))
        if main:
            by_title[main].append((target, False))
        for number in target.isbn:
            by_isbn[re.sub(r"[^0-9X]", "", number.upper())].append(target)
    found: dict[str, list[tuple[str, Book]]] = defaultdict(list)
    counts: Counter[str] = Counter()
    for book in books_found:
        counts["kbr books"] += 1
        for number in book.isbn:
            for target in by_isbn.get(number, []):
                found[target.key].append(("isbn", book))
        whole, main = _keys(book.title)
        for key in {whole, main} - {""}:
            for target, target_whole in by_title.get(key, []):
                if basis := _check(target, book, target_whole and key == whole):
                    found[target.key].append((basis, book))
    matches = []
    for target in wanted:
        fits = found.get(target.key)
        if not fits:
            continue
        exact = [fit for fit in fits if fit[0] == "isbn"]
        fits = exact or fits
        if len({tuple(book.isbn) for _, book in fits}) > 1:
            with_isbn = [fit for fit in fits if fit[1].isbn]
            if target.year and len({tuple(book.isbn) for _, book in fits if book.shelf_year == target.year}) == 1:
                fits = [fit for fit in fits if fit[1].shelf_year == target.year]
            elif (target.year and target.year >= ISBN_FROM and len({tuple(book.isbn) for _, book in with_isbn}) == 1
                  and all(book.shelf_year is None or abs(book.shelf_year - target.year) <= 1 for _, book in with_isbn)):
                fits = with_isbn  # one book, held more than once: the copies without an ISBN are no other edition
            else:
                counts["several editions (left out)"] += 1
                continue
        basis, book = sorted(fits, key=lambda fit: ("isbn", "author", "publisher").index(fit[0]))[0]
        counts[f"by {basis}"] += 1
        matches.append(KbrMatch(target.key, target.chapters, book.number, book.isbn, basis, book.shelf_year, target.year,
                                target.title, book.title, book.creators))
    counts["targets"] = len(wanted)
    return matches, dict(counts)


MATCH_COLUMNS = ["id", "chapters", "kbr", "isbn", "basis", "shelf_year", "year", "ours", "theirs", "creators"]


def write_matches(path: Path, matches: list[KbrMatch]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(MATCH_COLUMNS)
        for found in matches:
            writer.writerow([found.key, ";".join(found.chapters), found.number, ";".join(found.isbn), found.basis,
                             found.shelf_year or "", found.year or "", found.ours, found.theirs, " | ".join(found.creators)])


def name_index(records, books_found) -> dict[str, list[list]]:
    """Every person KBR names whose family name occurs in the bibliography, by folded family name: the given name,
    birth and death year. For deciding whether a family name and initial can be one person only."""
    families = {fold(person.family) for record in records for person in record.persons + (record.host.editors if record.host else [])}
    seen: dict[str, set[tuple]] = {}
    for book in books_found:
        for creator in book.creators:
            if (name := parse_name(creator)) and (key := fold(name.family)) in families:
                seen.setdefault(key, set()).add((name.given, name.born, name.died))
    return {key: sorted([list(item) for item in values], key=str) for key, values in seen.items()}


# --- The ermes record: year and authority ids -----------------------------------------------------------------------

_last = 0.0


def ermes(number: str, cache: Path, offline: bool = False) -> str | None:
    """The ``ermes`` record of a KBR book (cached, gzipped); None offline when it is not cached yet."""
    global _last
    path = cache / f"{number}.xml.gz"
    if path.exists():
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    if offline:
        return None
    url = f"{OAI}?{urllib.parse.urlencode({'verb': 'GetRecord', 'metadataPrefix': 'ermes', 'identifier': f'KBR{number}'})}"
    for attempt in range(6):
        time.sleep(max(0.0, _last + INTERVAL - time.monotonic()))
        _last = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=120) as response:
                text = response.read().decode("utf-8")
            break
        except (urllib.error.URLError, TimeoutError):
            if attempt == 5:
                return None
            time.sleep(10 * (attempt + 1))
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(text.encode("utf-8")))
    return text


_ERMES_FIELD = re.compile(r'<field name="([^"]+)">(.*?)</field>', re.S)


@dataclass
class Ermes:
    year: int | None = None
    publisher: str | None = None
    names: list[Name] = field(default_factory=list)


def parse_ermes(text: str) -> Ermes:
    found = Ermes()
    for name, value in _ERMES_FIELD.findall(text or ""):
        value = html.unescape(value)
        if name == "YearOfPublication" and found.year is None and (year := re.search(r"\b(1[5-9]\d\d|20\d\d)\b", value)):
            found.year = int(year.group(1))
        elif name == "Publisher" and found.publisher is None:
            found.publisher = squash(value)
        elif name == "Author_xml":
            number = re.search(r"<searchTerm>(\d+)</searchTerm>", value)
            label = re.search(r"<queryLabel>(.*?)</queryLabel>", value, re.S)
            if label and (person := parse_name(html.unescape(label.group(1)), number.group(1) if number else None)):
                found.names.append(person)
    return found


# --- Apply ----------------------------------------------------------------------------------------------------------

KBR_LINK = "https://uurl.kbr.be/bib/"


def _name_of(person, names: list[Name]) -> Name | None:
    fits = [name for name in names if same_name(person.family, name.family) and fold(person.family)[:1] == fold(name.family)[:1]
            and (not person.given or name_fits(person.given, name.given) or name_fits(name.given, person.given))]
    return fits[0] if len(fits) == 1 else None


def _fill(person, name: Name, source: str) -> bool:
    """Write KBR's form of the name onto a person; True when it wrote a given name out."""
    person.kbr_id = name.kbr_id or person.kbr_id
    person.dates = name.dates
    person.name_from = source
    if not written_out(person.given) and written_out(name.given) and name_fits(person.given, name.given) and _parts(person.given) != _parts(name.given):
        person.given_full = name.given
        return True
    return False


def apply_kbr(records, folder: Path, cache: Path) -> dict[str, int]:
    """Write ``kbr.csv`` into the records: the KBR link, the ISBN where the entry has none, and the authors' names
    as KBR writes them, on the matched book and then elsewhere (``carry_names``). A match whose ermes record gives a
    year more than one year off the entry's is dropped."""
    from collections import Counter

    by_id = {record.id: record for record in records}
    counts: Counter[str] = Counter()
    for record in records:
        record.kbr = None
        record.identifiers_from.pop("kbr", None)
        for person in record.persons + (record.host.editors if record.host else []):
            person.given_full = person.dates = person.kbr_id = person.name_from = None
        if record.identifiers_from.get("isbn", "").startswith("kbr"):
            record.isbn = []
            record.identifiers_from.pop("isbn")
    path = folder / "kbr.csv"
    if not path.exists():
        return {}
    for row in csv.DictReader(path.open(encoding="utf-8")):
        detail = parse_ermes(ermes(row["kbr"], cache, offline=True) or "")
        year = int(row["year"]) if row["year"] else None
        if detail.year and year and abs(detail.year - year) > 1:
            counts["dropped: another year"] += 1
            continue
        volume = row["id"].startswith("volume:")
        isbn = [value for value in row["isbn"].split(";") if value]
        names = detail.names or [name for name in map(parse_name, row["creators"].split(" | ")) if name]
        chosen = [by_id[key] for key in (row["chapters"].split(";") if volume else [row["id"]]) if key in by_id]
        for record in chosen:
            record.kbr = row["kbr"]
            record.identifiers_from["kbr"] = "kbr-volume" if volume else "kbr"
            counts["kbr link (volume)" if volume else "kbr link"] += 1
            if isbn and not record.isbn:
                record.isbn = list(isbn)
                record.identifiers_from["isbn"] = "kbr-volume" if volume else "kbr"
                counts["isbn from kbr (volume)" if volume else "isbn from kbr"] += 1
            # The volume's editors are named on its chapters too; a chapter's own authors are not in KBR's record.
            people = (record.host.editors if record.host else []) + [person for person in record.persons if person.role == "editor"] if volume else record.persons
            for person in people:
                if (name := _name_of(person, names)) is not None:
                    counts["persons matched"] += 1
                    counts["given names written out"] += _fill(person, name, "kbr")
    # A chapter whose volume has its own record, matched to KBR, takes the volume's link and ISBN.
    for record in records:
        volume = by_id.get(record.host.id or "") if record.type == "chapter" and record.host else None
        if volume is None or not volume.kbr or record.kbr:
            continue
        record.kbr = volume.kbr
        record.identifiers_from["kbr"] = "kbr-volume"
        counts["kbr link (volume)"] += 1
        if volume.isbn and not record.isbn and volume.identifiers_from.get("isbn") == "kbr":
            record.isbn = list(volume.isbn)
            record.identifiers_from["isbn"] = "kbr-volume"
            counts["isbn from kbr (volume)"] += 1
    names_file = folder / "kbr-names.json"
    known = json.loads(names_file.read_text(encoding="utf-8")) if names_file.exists() else {}
    counts.update(carry_names(records, known))
    return dict(counts)


ADULT = 18  # no publication before this age


def carry_names(records, known: dict[str, list[list]]) -> dict[str, int]:
    """Give a name printed with initials ("Prevenier, W.") on other entries the full name found on a matched book,
    when it can only be that person: of everyone the matched books, the bibliography's written-out names and all of
    KBR give for that family name, one person only fits the initials; and the entry falls within that person's
    life."""
    from collections import Counter, defaultdict

    counts: Counter[str] = Counter()
    found: dict[str, dict[str, Name]] = defaultdict(dict)  # folded family -> first given name -> person
    own: dict[str, set[str]] = defaultdict(set)  # folded family -> written-out given names in the bibliography
    every = [(record, person) for record in records for person in record.persons + (record.host.editors if record.host else [])]
    for record, person in every:
        family = fold(person.family)
        if person.name_from == "kbr" and (given := person.given_full or (person.given if written_out(person.given) else "")):
            found[family].setdefault(_parts(given)[0], Name(person.family, given, *_life(person.dates), person.kbr_id))
        if written_out(person.given):
            own[family].add(person.given)
    for record, person in every:
        family = fold(person.family)
        if person.name_from or written_out(person.given) or not person.given or family not in found:
            continue
        fits = [name for name in found[family].values() if name_fits(person.given, name.given)]
        if len(fits) != 1:
            continue
        name = fits[0]
        if _parts(person.given) == _parts(name.given):
            continue  # "Michel." is Michel already
        first = _parts(name.given)[0]
        others = {_parts(given)[0] for given in own[family] if name_fits(person.given, given)}
        others |= {_parts(given)[0] for given, *_ in known.get(family, []) if written_out(given) and name_fits(person.given, given)}
        # A name with one letter misread is the OCR's ("Waiter" for Walter), not a namesake; one letter more or less
        # can be one ("Jan", "Jean").
        if {other for other in others if len(other) != len(first) or Levenshtein.distance(other, first) > 1}:
            counts["names left out: namesakes"] += 1
            continue
        year = record.year or record.bgb_year
        if year and ((name.died and year > name.died + 1) or (name.born and year < name.born + ADULT)):
            counts["names left out: outside the lifetime"] += 1
            continue
        person.given_full, person.dates, person.kbr_id, person.name_from = name.given, name.dates, name.kbr_id, "kbr-name"
        counts["given names written out elsewhere"] += 1
    return dict(counts)


def _life(dates: str | None) -> tuple[int | None, int | None]:
    born, _, died = (dates or "").partition("-")
    return (int(born) if born else None, int(died) if died else None)
