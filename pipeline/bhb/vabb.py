"""Matching entries to the VABB-SHW, the Flemish Academic Bibliography for the Social Sciences and Humanities.

The open data of ECOOM (Zenodo, CC BY 4.0) lists publications by researchers at Flemish universities with their
DOI, ISBN and ISSN. Editions VIII (2000–2017), IX (2008–2017) and 15 (2014–2023) are read from
``build/external/vabb-08``, ``vabb-09`` and ``vabb-15``; a publication in several editions is merged by its id.

A VABB publication is turned into the shape of a Crossref item, so candidates are scored and accepted by exactly the
rules of ``bhb.identifiers``: title, author, year, journal or book, and first page.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from bhb.identifiers import Match, _full_title, accept, score
from bhb.textutil import fold

EDITIONS = ("vabb-15", "vabb-09", "vabb-08")  # newest first: its values win when editions differ
TYPES = {"1": "article", "2": "book", "3": "book", "4": "chapter", "5": "chapter"}
# Title words in more publications than this do not pick candidates.
COMMON = 1500
# VABB is a curated bibliography of the same field with full author lists, so its titles may differ a little more
# than Crossref's (a reworded subtitle, a dropped article) before a candidate is refused: 90 counts as the same
# title (Crossref: 95). Close stays at 85, as for Crossref: between 80 and 85 a hand check found other chapters of
# the same book, another text by the same author and the edition in another language.
TITLE_SAME = 90
TITLE_CLOSE = 85


@dataclass
class Publication:
    id: str
    title: str
    type: str
    year: int | None
    pages: str | None = None
    families: list[str] = field(default_factory=list)
    editors: list[str] = field(default_factory=list)
    container: str = ""
    doi: str | None = None
    isbn: list[str] = field(default_factory=list)
    issn: list[str] = field(default_factory=list)
    disciplines: list[str] = field(default_factory=list)
    language: str = ""

    def as_item(self) -> dict:
        """The publication as a Crossref item, for ``bhb.identifiers.score``."""
        return {
            "DOI": self.doi, "title": [self.title], "author": [{"family": family} for family in self.families],
            "editor": [{"family": family} for family in self.editors],
            "container-title": [self.container] if self.container else [], "page": self.pages,
            "issued": {"date-parts": [[self.year]]} if self.year else {},
        }


def _rows(path: Path):
    csv.field_size_limit(sys.maxsize)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def normalise_doi(value: str | None) -> str | None:
    """VABB writes DOIs in several ways: "doi:10.…", "http://dx.doi.org/10.…", with a trailing full stop."""
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", (value or "").strip().lower()).rstrip(".")
    return doi if doi.startswith("10.") else None


def _family(name: str) -> str:
    """"Gerwen, Van, Jef [1952 - 2002] [a::…]" → "Van Gerwen"; "VERELST, KARIN" → "Verelst"."""
    name = re.sub(r"\[[^\]]*\]", "", name).strip()
    parts = [part.strip() for part in name.split(",") if part.strip()]
    if not parts:
        return ""
    family = parts[0]
    if len(parts) >= 3 and parts[1][:1].isupper() and len(parts[1].split()) <= 2 and parts[1].lower().split()[0] in {"van", "de", "der", "den", "le", "la", "du", "von", "vander", "vanden", "d'"}:
        family = f"{parts[1]} {family}"
    return family.title() if family.isupper() else family


def load(root: Path) -> dict[str, Publication]:
    """Every VABB publication of the downloaded editions, by id."""
    pubs: dict[str, Publication] = {}
    journals: dict[str, str] = {}
    named: set[str] = set()
    for edition in EDITIONS:
        folder = root / edition
        for row in _rows(folder / "vabb_journals.csv"):
            journals.setdefault(row["vabb_standardnumbers_number"], row["vabb_journals_description"])
        for row in _rows(folder / "vabb_publications.csv"):
            pid = row["vabb_publications_id"]
            if pid in pubs:
                continue
            start, end = row.get("vabb_publications_startpage") or "", row.get("vabb_publications_endpage") or ""
            start = re.sub(r"^\D+", "", start)
            pubs[pid] = Publication(
                id=pid, title=row["vabb_publications_title"], year=int(row["vabb_publications_publicationyear"] or 0) or None,
                type=TYPES.get(row["vabb_publications_publicationtype"].replace("VABB-", ""), "other"),
                pages=f"{start}-{end}" if start else None,
                container=row.get("vabb_publications_booktitle") or row.get("vabb_publications_proceedings_title") or "",
                doi=normalise_doi(row.get("vabb_publications_doi")),
                language=row.get("vabb_publications_language") or "",
            )
            if not pubs[pid].container and pubs[pid].type == "article":
                pubs[pid].container = row.get("vabb_publications_pubjour") or ""
        labels = {row["vabb_disciplines_id"]: row["vabb_disciplines_shortlabel_en"] for row in _rows(folder / "vabb_disciplines.csv")}
        for row in _rows(folder / "vabb_publications_disciplines.csv"):
            pub = pubs.get(row["vabb_publications_id"])
            label = labels.get(row["vabb_disciplines_id"])
            if pub and label and label not in pub.disciplines:
                pub.disciplines.append(label)
        for row in _rows(folder / "vabb_containers.csv"):
            pub = pubs.get(row["vabb_publications_id"])
            if pub and not pub.container and row["vabb_containers_type"] in ("Book Title", "Proceedings Title"):
                pub.container = row["vabb_containers_value"]
        for row in _rows(folder / "vabb_additionalid.csv"):
            pub = pubs.get(row["vabb_publications_id"])
            if pub and row["vabb_additionalid_type"] == "DOI" and not pub.doi:
                pub.doi = normalise_doi(row["vabb_additionalid_value"])
        for row in _rows(folder / "vabb_publications_standardnumbers.csv"):
            pub = pubs.get(row["vabb_publications_id"])
            if not pub:
                continue
            number, kind = row["vabb_standardnumbers_number"], row["vabb_standardnumbers_type"]
            target = pub.issn if kind == "ISSN" else pub.isbn if kind == "ISBN" else None
            if target is not None and number not in target:
                target.append(number)
        for row in _rows(folder / "vabb_authors.csv"):
            pub = pubs.get(row["vabb_publications_id"])
            if not pub or pub.id in named:
                continue
            if "vabb_authors_name" in row:
                target = pub.families if row["vabb_authors_type"] == "Author" else pub.editors if row["vabb_authors_type"] == "Editor" else None
                if target is not None:
                    target.append(_family(row["vabb_authors_name"]))
            else:
                pub.families = [_family(name) for name in (row.get("vabb_authors_authors") or "").split(";") if name.strip()]
                pub.editors = [_family(name) for name in (row.get("vabb_authors_editors") or "").split(";") if name.strip()]
        # Each edition lists a publication's people completely, so the first edition that has them is kept.
        named.update(pub.id for pub in pubs.values() if pub.families or pub.editors)
    # IX and 15 name an article's journal only through its ISSN.
    for pub in pubs.values():
        if pub.type == "article" and not pub.container:
            pub.container = next((journals[number] for number in pub.issn if number in journals), "")
    return pubs


class Index:
    """Candidates by rare title words, so each entry is compared with a handful of publications, not 100,000."""

    def __init__(self, pubs: dict[str, Publication]):
        self.pubs = pubs
        self.postings: dict[str, list[str]] = defaultdict(list)
        for pub in pubs.values():
            for word in set(_words(pub.title)):
                self.postings[word].append(pub.id)

    def candidates(self, title: str, year: int | None, limit: int = 5, subtitle: str | None = None) -> list[Publication]:
        """The publications sharing the rarest words of the title (and of the subtitle, which VABB may join to it),
        closest first, compared with the title alone and with title and subtitle, as VABB may give either."""
        found = {pid for text, n in ((title, 3), (subtitle or "", 2)) for word in self._rare(text)[:n] for pid in self.postings[word]}
        pubs = [self.pubs[pid] for pid in found if year is None or self.pubs[pid].year is None or abs(self.pubs[pid].year - year) <= 1]
        targets = [fold(title)] + ([fold(f"{title} {subtitle}")] if subtitle else [])
        pubs.sort(key=lambda pub: max(fuzz.ratio(target, fold(pub.title)) for target in targets), reverse=True)
        return pubs[:limit]

    def _rare(self, text: str) -> list[str]:
        return sorted((word for word in set(_words(text)) if 0 < len(self.postings.get(word, ())) <= COMMON), key=lambda word: len(self.postings[word]))


def _words(title: str) -> list[str]:
    return [word for word in fold(title).split() if len(word) >= 4]


def match(record, index: Index) -> tuple[Match, Publication | None]:
    ours = _full_title(record.title, record.subtitle)
    best: tuple[tuple, dict, Publication] | None = None
    for pub in index.candidates(record.title or "", record.year, subtitle=record.subtitle):
        features = score(record, pub.as_item())
        rank = (accept(features, len(ours), TITLE_SAME, TITLE_CLOSE), features["title"])
        if best is None or rank > best[0]:
            best = (rank, features, pub)
    if best is None:
        return Match(record.id, None, {}, False, ours, "", ""), None
    _, features, pub = best
    return Match(record.id, pub.doi, features, accept(features, len(ours), TITLE_SAME, TITLE_CLOSE), ours, pub.title, pub.container), pub
