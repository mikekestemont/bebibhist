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
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from bhb.textutil import fold

API = "https://api.crossref.org/works"
# Crossref asks clients to identify themselves; the project page is the contact, no personal address is sent.
USER_AGENT = "bebibhist/0.1 (https://github.com/mikekestemont/bebibhist)"
# The public pool allows one request per second, one at a time (its x-rate-limit headers, October 2026); requests
# start at least this many seconds apart.
INTERVAL = 1.05
_last_start = 0.0
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


def query_params(record) -> dict[str, str] | None:
    """The Crossref query for one entry, or None when it has no title or year."""
    title = _full_title(record.title, record.subtitle)
    if not title or not record.year:
        return None
    first = _first_author(record)
    host = record.host.title if record.host and record.host.title else ""
    words = " ".join(part for part in (title, first or "", host) if part)
    return {
        "query.bibliographic": words[:400],
        "filter": f"from-pub-date:{record.year - 1},until-pub-date:{record.year + 1}",
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
        time.sleep(max(0.0, _last_start + INTERVAL - time.monotonic()))
        _last_start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
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


def _year(item: dict) -> int | None:
    for key in ("published-print", "issued", "published-online"):
        parts = (item.get(key) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def _first_page(pages: str | None) -> str | None:
    match = re.match(r"\D*(\d+)", pages or "")
    return match.group(1) if match else None


def score(record, item: dict) -> dict[str, float | bool | None]:
    """How well a Crossref item fits an entry. ``None`` means the field is missing on one side."""
    ours = fold(_full_title(record.title, record.subtitle))
    their_title = " ".join(item.get("title") or [])
    their_full = fold(_full_title(their_title, " ".join(item.get("subtitle") or [])))
    title = max(fuzz.ratio(ours, their_full), fuzz.ratio(fold(record.title or ""), fold(their_title))) if ours and their_full else 0.0
    people = [fold(person.get("family", "")) for person in (item.get("author") or []) + (item.get("editor") or [])]
    first = fold(_first_author(record) or "")
    if first and people:
        author: bool | None = any(first == family or first in family.split() or family in first.split() for family in people if family)
    else:
        author = None
    year = _year(item)
    host = fold(record.host.title) if record.host and record.host.title else ""
    container = fold(" ".join(item.get("container-title") or []))
    page = _first_page(record.host.pages if record.host else None)
    their_page = _first_page(item.get("page"))
    return {
        "title": round(title, 1),
        "author": author,
        "year": abs(year - record.year) <= 1 if year and record.year else None,
        "container": round(fuzz.partial_ratio(host, container), 1) if host and container else None,
        "page": page == their_page if page and their_page else None,
    }


# A title this short ("Belgium", "Introduction") needs the journal or the first page to agree as well.
SHORT_TITLE = 30


def accept(features: dict[str, float | bool | None], title_length: int = SHORT_TITLE) -> bool:
    """A DOI is stored when the title is the same, or close enough for an OCR error, and enough of author, year,
    journal and first page agree. A different author or year rejects the candidate. A different journal name does
    not, since Crossref often names the series or an abbreviation (BMGN, WT) where the volume has the full title; a
    different first page rejects it unless the journal agrees."""
    if features["title"] < TITLE_CLOSE or features["author"] is False or features["year"] is False:
        return False
    container = features["container"] >= 80 if features["container"] is not None else None
    if features["page"] is False and not container:
        return False
    support = sum(check is True for check in (features["author"], features["year"], container, features["page"]))
    if title_length < SHORT_TITLE and not (container or features["page"]):
        return False
    return support >= 2 if features["title"] >= TITLE_SAME else support >= 3


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
    matches = []
    for index, record in enumerate(records):
        params = query_params(record)
        matches.append(best_match(record, fetch(params, cache)) if params else Match(record.id, None, {}, False, record.title or "", "", ""))
        if progress and (index + 1) % 100 == 0:
            progress(index + 1)
    return matches
