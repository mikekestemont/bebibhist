"""ISBNs for books from Open Library (`docs/IDENTIFIER_PROPOSAL.md`, step E3).

A book from 1970 on without an ISBN is looked up by title and first author or editor. Open Library groups the
editions of a work, and a work with several editions (a reprint, a translation) has several ISBNs, of which only one
is ours; so a work is accepted only when it has a single edition, and when its title, author and one of its years of
publication agree with the entry. Answers are cached in ``build/cache/openlibrary/``; Open Library asks for at most
one request a second.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from bhb.identifiers import USER_AGENT, _first_author, _first_editor, _full_title, same_name
from bhb.textutil import fold

API = "https://openlibrary.org/search.json"
FIELDS = "key,title,subtitle,author_name,first_publish_year,publish_year,isbn,edition_count,publisher"
INTERVAL = 1.05
TITLE_SAME = 95
_last = 0.0


@dataclass
class BookMatch:
    record_id: str
    accepted: bool
    isbn: list[str]
    work: str
    title: float
    author: bool | None
    year: bool | None
    editions: int
    ours: str
    theirs: str


def query(record) -> dict[str, str] | None:
    if not record.title:
        return None
    name = _first_author(record) or _first_editor(record) or ""
    words = " ".join(part for part in (record.title, name) if part)
    return {"q": words[:300], "fields": FIELDS, "limit": "5"}


def fetch(params: dict[str, str], cache: Path) -> dict:
    global _last
    url = f"{API}?{urllib.parse.urlencode(params)}"
    path = cache / f"{hashlib.sha1(url.encode()).hexdigest()}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    for attempt in range(5):
        time.sleep(max(0.0, _last + INTERVAL - time.monotonic()))
        _last = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == 4:
                return {"docs": []}
            time.sleep(5 * (attempt + 1))
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def score(record, doc: dict) -> BookMatch:
    ours = _full_title(record.title, record.subtitle)
    theirs = _full_title(doc.get("title"), doc.get("subtitle"))
    title = max(fuzz.ratio(fold(ours), fold(theirs)), fuzz.ratio(fold(record.title or ""), fold(doc.get("title") or "")))
    name = _first_author(record) or _first_editor(record)
    authors = doc.get("author_name") or []
    author = any(same_name(name, author_name.split()[-1]) or same_name(name, author_name) for author_name in authors) if name and authors else None
    years = set(doc.get("publish_year") or []) | ({doc["first_publish_year"]} if doc.get("first_publish_year") else set())
    year = record.year in years if record.year and years else None
    editions = int(doc.get("edition_count") or 0)
    isbn = sorted(set(doc.get("isbn") or []))
    accepted = (title >= TITLE_SAME and author is not False and year is True and editions == 1 and 1 <= len(isbn) <= 2
                and (author is True or len(ours) >= 40))
    return BookMatch(record.id, accepted, isbn if accepted else [], doc.get("key", ""), round(title, 1), author, year, editions, ours, theirs)


def match(record, cache: Path) -> BookMatch | None:
    params = query(record)
    if not params:
        return None
    scored = [score(record, doc) for doc in fetch(params, cache).get("docs") or []]
    if not scored:
        return None
    scored.sort(key=lambda found: (found.accepted, found.title), reverse=True)
    return scored[0]


def books(records) -> list:
    return [record for record in records if record.role == "entry" and record.type == "book" and record.title
            and (record.year or 0) >= 1970 and not record.isbn]
