"""DOIs from Crossref for articles and chapters (step E0–E2 of ``docs/IDENTIFIER_PROPOSAL.md``).

Each entry is looked up once by its title, first author, journal or volume and year; every response is cached in
``build/cache/crossref/`` so a run can stop and resume, and a rebuild does not query again. A candidate is scored on
the title, the author, the year, the journal and the first page, and accepted only when the title and at least two
of the others agree. Nothing here changes ``printed``: a matched title that differs from ours by a few letters is a
proposal to correct an OCR error, not a correction.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from bhb.textutil import fold

API = "https://api.crossref.org/works"
# Crossref asks clients to identify themselves. With a contact address in ``BHB_CONTACT`` (never in the code), the
# queries go to its faster "polite" pool; the address goes in the User-Agent, not the URL, so the cache keys stay the
# same either way.
CONTACT = os.environ.get("BHB_CONTACT", "").strip()
USER_AGENT = "bebibhist/0.1 (https://github.com/mikekestemont/bebibhist" + (f"; mailto:{CONTACT})" if CONTACT else ")")
# The public pool allows one request per second, one at a time (its x-rate-limit headers, October 2026); the polite
# pool more. Requests start at least this many seconds apart; ``pace`` adapts it to the headers of the first answer.
INTERVAL = 1.05
# Requests at once: one in the public pool, three in the polite pool (its x-concurrency-limit).
WORKERS = 3 if CONTACT else 1
_last_start = 0.0
_lock = threading.Lock()
FIELDS = "DOI,title,subtitle,author,editor,container-title,issued,published-print,published-online,volume,issue,page,type,ISSN,ISBN"

# A title this similar to a candidate's counts as the same title; below it, the OCR has to explain the difference.
TITLE_SAME = 95
TITLE_CLOSE = 85


@dataclass
class Match:
    record_id: str
    doi: str | None
    score: dict[str, float | bool | None]
    accepted: bool
    our_title: str
    their_title: str
    their_container: str


def _full_title(title: str | None, subtitle: str | None) -> str:
    return ": ".join(part for part in (title, subtitle) if part)


# "s.n." (sine nomine) and its kin stand for a missing author, not a name.
_NO_NAME = {"s n", "sn", "anon", "anonyme", "anoniem", "anonymous", "x", "n n", "nn"}


def _first_author(record) -> str | None:
    for person in record.persons:
        if person.role == "author" and fold(person.family) not in _NO_NAME:
            return person.family
    return None


def _first_editor(record) -> str | None:
    return next((person.family for person in record.persons if person.role == "editor" and fold(person.family) not in _NO_NAME), None)


def _compact(name: str) -> str:
    return fold(name).replace(" ", "").replace("ij", "y")


def same_name(ours: str, theirs: str) -> bool:
    """Family names that are one name in two spellings: spaces ("Van Bruaene", "Vanbruaene"), ij and y ("Dijck",
    "Dyck"), a particle dropped ("Van Dyck", "Dijck") or a letter misread by the OCR ("Godderis", "Goddeeris")."""
    left, right = _compact(ours), _compact(theirs)
    if not left or not right:
        return False
    if left == right or (min(len(left), len(right)) >= 4 and (left.endswith(right) or right.endswith(left))):
        return True
    return min(len(left), len(right)) >= 5 and fuzz.ratio(left, right) >= 80


def _journal_issn(record) -> str | None:
    """The ISSN of an article's journal, when ``bhb journals apply`` found one."""
    journal = getattr(record, "journal_id", None) or ""
    return journal[5:] if journal.startswith("issn:") else None


def query_params(record, in_journal: bool = False) -> dict[str, str] | None:
    """The Crossref query for one entry, or None when it has no title or year. With ``in_journal``, an article whose
    journal has an ISSN is looked for in that journal only."""
    title = _full_title(record.title, record.subtitle)
    if not title or not record.year:
        return None
    first = _first_author(record)
    host = record.host.title if record.host and record.host.title else ""
    words = " ".join(part for part in (title, first or "", host) if part)
    issn = _journal_issn(record) if in_journal else None
    return {
        "query.bibliographic": words[:400],
        "filter": f"from-pub-date:{record.year - 1},until-pub-date:{record.year + 1}" + (f",issn:{issn}" if issn else ""),
        "rows": "5",
        "select": FIELDS,
    }


def fetch(params: dict[str, str], cache: Path) -> dict:
    """One Crossref query, from the cache when it was asked before."""
    url = f"{API}?{urllib.parse.urlencode(params)}"
    path = cache / f"{hashlib.sha1(url.encode()).hexdigest()}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    global _last_start
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        with _lock:
            time.sleep(max(0.0, _last_start + INTERVAL - time.monotonic()))
            _last_start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
                _pace(response.headers)
            break
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
            wait = error.headers.get("Retry-After") if error.headers else None
            time.sleep(float(wait) if wait and wait.isdigit() else 2 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
            time.sleep(5 * (attempt + 1))
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _pace(headers) -> None:
    """Space requests as the rate-limit headers allow: ``x-rate-limit-limit`` requests per ``x-rate-limit-interval``."""
    global INTERVAL
    limit, interval = headers.get("x-rate-limit-limit"), headers.get("x-rate-limit-interval", "1s")
    if limit and limit.isdigit() and int(limit) > 0 and interval.endswith("s") and interval[:-1].isdigit():
        INTERVAL = int(interval[:-1]) / int(limit) * 1.05


def _cached(params: dict[str, str], cache: Path) -> dict | None:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    path = cache / f"{hashlib.sha1(url.encode()).hexdigest()}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def candidates(record, cache: Path, offline: bool = False) -> dict:
    """Crossref's answer for an entry. A printed article in a journal with an ISSN is looked for in that journal
    first, and only when that finds nothing in all of Crossref; the catalogue years keep their plain query (and their
    cache). ``offline`` reads only the cache, for the steps that use answers already fetched."""
    queries = []
    if record.source.startswith("print") and _journal_issn(record):
        queries.append(query_params(record, in_journal=True))
    queries.append(query_params(record))
    for params in queries:
        data = _cached(params, cache) if offline else fetch(params, cache)
        if data and (data.get("message") or {}).get("items"):
            return data
    return {"message": {"items": []}}


def _year(item: dict) -> int | None:
    for key in ("published-print", "issued", "published-online"):
        parts = (item.get(key) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def _first_page(pages: str | None) -> str | None:
    match = re.match(r"\D*(\d+)", pages or "")
    return match.group(1) if match else None


_FUNCTION_WORDS = {
    "nl": {"de", "het", "een", "van", "en", "voor", "met", "over", "naar", "bij", "uit", "tot", "op"},
    "en": {"the", "of", "and", "a", "an", "for", "with", "from", "to", "on", "between"},
    "fr": {"le", "la", "les", "des", "du", "et", "une", "un", "pour", "sur", "dans", "aux", "au"},
    "de": {"der", "die", "das", "und", "im", "zur", "zum", "von", "mit", "über"},
}


def title_language(text: str) -> str | None:
    """The language whose function words a title uses most, when one clearly leads; None for a title too short or
    too mixed to tell (a bilingual title, or names only)."""
    words = fold(text).split()
    counts = sorted(((sum(word in vocabulary for word in words), language) for language, vocabulary in _FUNCTION_WORDS.items()), reverse=True)
    (best, language), (second, _) = counts[0], counts[1]
    return language if best >= 2 and best >= 2 * second else None


def score(record, item: dict) -> dict[str, float | bool | None]:
    """How well a Crossref item fits an entry. ``None`` means the field is missing on one side."""
    ours = fold(_full_title(record.title, record.subtitle))
    their_title = " ".join(item.get("title") or [])
    their_full = fold(_full_title(their_title, " ".join(item.get("subtitle") or [])))
    title = max(fuzz.ratio(ours, their_full), fuzz.ratio(fold(record.title or ""), fold(their_title))) if ours and their_full else 0.0
    people = [person.get("family", "") for person in (item.get("author") or []) + (item.get("editor") or [])]
    # An edited volume has no author: its first editor stands in.
    first = _first_author(record) or _first_editor(record) or ""
    if first and any(people):
        author: bool | None = any(same_name(first, family) for family in people if family)
    else:
        author = None
    year = _year(item)
    host = fold(record.host.title) if record.host and record.host.title else ""
    container = fold(" ".join(item.get("container-title") or []))
    page = _first_page(record.host.pages if record.host else None)
    their_page = _first_page(item.get("page"))
    ours_language, their_language = title_language(_full_title(record.title, record.subtitle)), title_language(their_full)
    return {
        "title": round(title, 1),
        # The same publication in another language (a catalogue in a Dutch and an English edition) has its own ISBN.
        "language": ours_language == their_language if ours_language and their_language else None,
        # A book (no journal or volume, a publisher) is not a journal article of the same title: that is a review of it.
        "kind": False if not (record.host and record.host.title) and record.publisher and item.get("type") == "journal-article" else None,
        "author": author,
        "year": abs(year - record.year) <= 1 if year and record.year else None,
        # A candidate with the ISSN of the article's journal is in that journal, however either side spells it.
        "container": 100.0 if _journal_issn(record) and _journal_issn(record) in (item.get("ISSN") or [])
        else round(fuzz.partial_ratio(host, container), 1) if host and container else None,
        "page": page == their_page if page and their_page else None,
    }


# A title this short ("Belgium", "Introduction") needs the author and the journal or first page to agree as well.
SHORT_TITLE = 30


def accept(features: dict[str, float | bool | None], title_length: int = SHORT_TITLE, same: float = TITLE_SAME, close: float = TITLE_CLOSE) -> bool:
    """A DOI is stored when the title is the same, or close enough for an OCR error, and enough of author, year,
    journal and first page agree. A different author or year rejects the candidate. A different journal name does
    not, since Crossref often names the series or an abbreviation (BMGN, WT) where the volume has the full title; a
    different first page rejects it unless the journal agrees."""
    if features["title"] < close or features["author"] is False or features["year"] is False or features.get("language") is False or features.get("kind") is False:
        return False
    container = features["container"] >= 80 if features["container"] is not None else None
    if features["page"] is False and not container:
        return False
    support = sum(check is True for check in (features["author"], features["year"], container, features["page"]))
    # A short title ("Conclusion", "Belgium") is shared by many texts: the author must agree, and the journal or page.
    if title_length < SHORT_TITLE and not (features["author"] is True and (container or features["page"])):
        return False
    return support >= 2 if features["title"] >= same else support >= 3


def best_match(record, data: dict) -> Match:
    items = (data.get("message") or {}).get("items") or []
    ours = _full_title(record.title, record.subtitle)
    scored = [(score(record, item), item) for item in items]
    scored.sort(key=lambda pair: (accept(pair[0], len(ours)), pair[0]["title"]), reverse=True)
    if not scored:
        return Match(record.id, None, {}, False, ours, "", "")
    features, item = scored[0]
    their = _full_title(" ".join(item.get("title") or []), " ".join(item.get("subtitle") or []))
    return Match(record.id, item.get("DOI"), features, accept(features, len(ours)), ours, their, " ".join(item.get("container-title") or []))


def pilot_sample(records, size: int, seed: int = 1) -> list:
    """Articles and chapters from the most recent printed volume (2007) and the most recent catalogue years
    (2016–2017), half and half."""
    def wanted(record, source, years):
        return record.role == "entry" and record.type in ("article", "chapter") and record.source == source and record.bgb_year in years and record.title
    rng = random.Random(seed)
    printed = [record for record in records if wanted(record, "print-straive", {2007})]
    catalogue = [record for record in records if wanted(record, "vsmart", {2016, 2017})]
    return rng.sample(printed, min(size // 2, len(printed))) + rng.sample(catalogue, min(size - size // 2, len(catalogue)))


def run(records, cache: Path, progress=None) -> list[Match]:
    from concurrent.futures import ThreadPoolExecutor

    done = 0

    def one(record) -> Match:
        nonlocal done
        params = query_params(record)
        match = best_match(record, candidates(record, cache)) if params else Match(record.id, None, {}, False, record.title or "", "", "")
        with _lock:
            done += 1
            if progress and done % 100 == 0:
                progress(done)
        return match

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(one, records))


# --- writing the matches into the records ---------------------------------------------------------------------------

MATCH_FILES = ("vsmart.csv", "print-straive.csv", "print-pdf.csv", "print-sample.csv", "pilot.csv")
MISSING_HOST = "[host record not exported"


def _normal_issn(value: str) -> str | None:
    digits = re.sub(r"[^0-9Xx]", "", value or "").upper()
    return f"{digits[:4]}-{digits[4:]}" if len(digits) == 8 else None


def apply_identifiers(records, folder: Path, cache: Path) -> dict[str, int]:
    """Write the accepted matches into the records: the DOI from Crossref (it wins when VABB gives another), ISSNs
    and ISBNs from both, and for an article whose journal record was not exported, the journal name its own match or
    another article of the same missing journal gives. Every value records its source in ``identifiers_from``; the
    printed citation is not touched."""
    import csv
    from collections import Counter, defaultdict

    from bhb.vabb import normalise_doi

    by_id = {record.id: record for record in records}
    counts: Counter[str] = Counter()
    for record in records:
        record.doi, record.isbn, record.issn, record.identifiers_from = None, [], [], {}
        if "host-title-matched" in record.provenance.flags:
            record.provenance.flags.remove("host-title-matched")
            record.host.title = f"{MISSING_HOST}]"
    host_names: dict[str, Counter[str]] = defaultdict(Counter)

    def add(record, kind: str, values: list[str], source: str) -> None:
        target = record.isbn if kind == "isbn" else record.issn
        for value in values:
            if value and value not in target:
                target.append(value)
                record.identifiers_from.setdefault(kind, source)

    for name in MATCH_FILES:
        path = folder / name
        if not path.exists():
            continue
        for row in csv.DictReader(path.open(encoding="utf-8")):
            record = by_id.get(row["id"])
            if row["accepted"] != "1" or record is None or record.doi:
                continue
            item = next((i for i in candidates(record, cache, offline=True)["message"]["items"] if i.get("DOI") == row["doi"]), None)
            if item is None:
                continue
            record.doi = item["DOI"].lower()
            record.identifiers_from["doi"] = "crossref"
            add(record, "issn", [_normal_issn(value) for value in item.get("ISSN") or []], "crossref")
            add(record, "isbn", item.get("ISBN") or [], "crossref")
            if record.host and (record.host.title or "").startswith(MISSING_HOST) and item.get("container-title"):
                host_names[record.host.id or record.id][" ".join(item["container-title"])] += 1
            counts["doi from crossref"] += 1
    vabb = folder / "vabb.csv"
    if vabb.exists():
        for row in csv.DictReader(vabb.open(encoding="utf-8")):
            record = by_id.get(row["id"])
            if row["accepted"] != "1" or record is None:
                continue
            doi = normalise_doi(row["doi"])
            # Only for articles: for a book VABB can carry the DOI of a review, for a chapter the book's DOI.
            if doi and not record.doi and record.type == "article":
                record.doi = doi
                record.identifiers_from["doi"] = "vabb"
                counts["doi from vabb"] += 1
            add(record, "issn", [_normal_issn(value) for value in row["issn"].split(";")], "vabb")
            add(record, "isbn", [value for value in row["isbn"].split(";") if value], "vabb")
            if record.host and (record.host.title or "").startswith(MISSING_HOST) and row["their_container"]:
                host_names[record.host.id or record.id][row["their_container"]] += 1
    # A journal name for the articles of a missing journal record, when the matches agree on it.
    for record in records:
        names = host_names.get((record.host.id or record.id) if record.host else "")
        if not names or not (record.host.title or "").startswith(MISSING_HOST):
            continue
        name, votes = names.most_common(1)[0]
        if all(fuzz.partial_ratio(fold(name), fold(other)) >= 90 for other in names):
            record.host.title = re.sub(r"\s+\d+$", "", name.replace("&amp;", "&"))
            record.provenance.flags.append("host-title-matched")
            counts["journal name recovered"] += 1
    for record in records:
        counts["with an identifier"] += bool(record.doi or record.isbn or record.issn)
        counts["isbn"] += bool(record.isbn)
        counts["issn"] += bool(record.issn)
    return dict(counts)


# --- OCR proposals: where a matched source spells a word or name differently ---------------------------------------

_TAG = re.compile(r"<[^>]+>")


def _inside(left: str, right: str) -> bool:
    """The two spellings differ inside the word, as an OCR error does ("kleurijke", "kleurrijke"), not only in its
    ending, as a plural or a spelling convention does ("painting", "paintings"; "Centre", "Center")."""
    prefix = len(next((left[:n] for n in range(min(len(left), len(right)), 0, -1) if left[:n] == right[:n]), ""))
    return prefix < min(len(left), len(right)) - 2


def word_differences(ours: str, theirs: str) -> list[tuple[str, str]]:
    """Words of our title that the matched title spells slightly differently ("terrrein" / "terrein"); case,
    accents, punctuation and missing or added words do not count."""
    import difflib

    left = re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", ours)
    right = re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", _TAG.sub("", theirs))
    pairs = []
    matcher = difflib.SequenceMatcher(None, [fold(word) for word in left], [fold(word) for word in right], autojunk=False)
    for operation, i1, i2, j1, j2 in matcher.get_opcodes():
        if operation == "replace" and i2 - i1 == j2 - j1:
            for word, other in zip(left[i1:i2], right[j1:j2]):
                if fold(word) != fold(other) and len(word) >= 4 and fuzz.ratio(fold(word), fold(other)) >= 75 and _inside(fold(word), fold(other)):
                    pairs.append((word, other))
    return pairs


def ocr_proposals(records, folder: Path, cache: Path) -> list[dict]:
    """One row per word or author name in which an entry differs from the source it was matched to. Either side can
    be the misspelt one, so these are proposals for review or for the citation pass, never applied."""
    import csv

    from bhb.vabb import Index, load  # noqa: F401  (VABB names come from the matched publication)

    by_id = {record.id: record for record in records}
    rows: list[dict] = []
    vabb_pubs = None
    for name in (*MATCH_FILES, "vabb.csv"):
        path = folder / name
        if not path.exists():
            continue
        for row in csv.DictReader(path.open(encoding="utf-8")):
            record = by_id.get(row["id"])
            if row["accepted"] != "1" or record is None:
                continue
            source = "vabb" if name == "vabb.csv" else "crossref"
            for word, other in word_differences(row["ours"], row["theirs"]):
                rows.append({"id": record.id, "field": "title", "ours": word, "theirs": other, "source": source})
            if source == "crossref":
                item = next((i for i in candidates(record, cache, offline=True)["message"]["items"] if i.get("DOI") == row["doi"]), None)
                families = [person.get("family", "") for person in (item or {}).get("author") or []]
            else:
                if vabb_pubs is None:
                    vabb_pubs = load(folder.parent / "external")
                families = vabb_pubs[row["vabb_id"]].families if row.get("vabb_id") in vabb_pubs else []
            for person in record.persons:
                for family in families:
                    left, right = _compact(person.family), _compact(re.sub(r"\s+[A-Z]$", "", family.strip()))
                    # A particle or initial more or less ("van Rossem", "Rossem") is a convention, not a misreading.
                    if same_name(person.family, family) and left != right and not (left.endswith(right) or right.endswith(left)):
                        rows.append({"id": record.id, "field": "author", "ours": person.family, "theirs": family, "source": source})
    unique = {(row["id"], row["field"], row["ours"], row["theirs"]): row for row in rows}
    return list(unique.values())


# --- free to read: open access status by DOI ------------------------------------------------------------------------

OPENALEX = "https://api.openalex.org/works"
# Persée gives free access to everything it holds, though OpenAlex lists much of it as closed.
FREE_PREFIXES = {"10.3406": "persee"}


def open_access(records, cache: Path, batch: int = 50) -> dict[str, int]:
    """Mark entries whose DOI leads to a free copy (``free_to_read``, with ``identifiers_from["free"]``): OpenAlex's
    open-access status, or a DOI of Persée. Only the status is kept: the link stays the DOI, so the publisher keeps
    the address up to date. Answers are cached in ``cache`` (one file per batch of DOIs)."""
    from collections import Counter

    counts: Counter[str] = Counter()
    with_doi = [record for record in records if record.doi]
    for record in with_doi:
        record.free_to_read = None
        record.identifiers_from.pop("free", None)
    status: dict[str, bool] = {}
    dois = sorted({record.doi for record in with_doi})
    cache.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(dois), batch):
        chunk = dois[start:start + batch]
        params = {"filter": "doi:" + "|".join(chunk), "select": "doi,open_access", "per-page": str(batch)}
        url = f"{OPENALEX}?{urllib.parse.urlencode(params)}"
        path = cache / f"{hashlib.sha1(url.encode()).hexdigest()}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            request = urllib.request.Request(url, headers={"User-Agent": "bebibhist/0.1 (https://github.com/mikekestemont/bebibhist)"})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            path.write_text(json.dumps(data), encoding="utf-8")
            time.sleep(1.0)
        for work in data.get("results") or []:
            doi = (work.get("doi") or "").lower().replace("https://doi.org/", "")
            status[doi] = bool((work.get("open_access") or {}).get("is_oa"))
    for record in with_doi:
        prefix = FREE_PREFIXES.get(record.doi.split("/")[0])
        if prefix:
            record.free_to_read, record.identifiers_from["free"] = True, prefix
        elif status.get(record.doi):
            record.free_to_read, record.identifiers_from["free"] = True, "openalex"
        counts["free to read" if record.free_to_read else "not known to be free"] += 1
    counts["known to openalex"] = len(status)
    return dict(counts)
