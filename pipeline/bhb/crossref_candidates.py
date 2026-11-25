"""Candidates for the years still to be collected, from Crossref (`docs/IMPLEMENTATION_PLAN.md` §4j).

The articles of one year in the journals from which the bibliography took articles in earlier volumes, scored by the
model of ``bhb.vabb_candidates`` trained on the same journals' articles of the complete volumes 2018–2021: an article
matched to an entry is one the bibliography took. The candidates are machine-proposed, internal, and for review in the
same inbox as VABB's.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from bhb.identifiers import FIELDS, _year, fetch
from bhb.textutil import fold
from bhb.vabb import Index, Publication, match

# Journals that had an article in the volumes from this year on; a journal with more articles a year than LARGEST is
# left out (Sustainability, JAMA …: 13 journals, 23,000 articles of 2024, nine of the bibliography's in four years).
SINCE = 2015
LARGEST = 500
ROWS = 1000
TRAIN_YEARS = range(2018, 2021)
TEST_YEARS = range(2021, 2022)
# Under one in a hundred of these articles is the bibliography's, against one in twenty for VABB, so the groups start
# higher. By rank, 54–63 % of group A and 32–35 % of group B were in the volumes 2020 and 2021; below B, about a tenth.
GROUP_A = 0.9
THRESHOLD = 0.7
SOURCE = "Crossref"


def journals(records, issns: dict[str, list[str]]) -> dict[str, set[int]]:
    """The volumes since ``SINCE`` in which each journal with an ISSN had an article."""
    seen: dict[str, set[int]] = {}
    for record in records:
        if record.role == "entry" and record.type == "article" and record.journal_id in issns and (record.bgb_year or 0) >= SINCE:
            seen.setdefault(record.journal_id, set()).add(record.bgb_year)
    return seen


def _ask(filters: list[str], batch: list[str], ask, **more) -> dict:
    return ask({"filter": ",".join([*filters, *(f"issn:{issn}" for issn in batch)]), "rows": str(ROWS), "select": FIELDS, **more})["message"]


def _items(filters: list[str], groups: list[list[str]], ask) -> list[dict]:
    """Every article of these journals (each a list of ISSNs). An answer that does not hold them all is asked again in
    halves, so that each request stands on its own and can be repeated from the cache."""
    message = _ask(filters, [issn for group in groups for issn in group], ask)
    if message["total-results"] <= ROWS:
        return message["items"]
    if len(groups) > 1:
        half = len(groups) // 2
        return _items(filters, groups[:half], ask) + _items(filters, groups[half:], ask)
    return message["items"] + [item for offset in range(ROWS, message["total-results"], ROWS)
                               for item in _ask(filters, groups[0], ask, offset=str(offset), sort="published", order="asc")["items"]]


def harvest(year: int, groups: list[list[str]], ask, batch: int = 10) -> list[dict]:
    """The articles printed in ``year`` (or online only) in these journals. Crossref dates an article by its first
    appearance, so those online earlier and printed this year are asked for as well; of the entries of 2020–2021, the
    printed year is the volume's for 95 %, the first one for 91 %."""
    asked = [(["type:journal-article", f"from-pub-date:{year}-01-01", f"until-pub-date:{year}-12-31"], batch),
             (["type:journal-article", f"from-print-pub-date:{year}-01-01", f"until-print-pub-date:{year}-12-31", f"until-pub-date:{year - 1}-12-31"], 4 * batch)]
    found: dict[str, dict] = {}
    for filters, size in asked:
        for start in range(0, len(groups), size):
            for item in _items(filters, groups[start:start + size], ask):
                if item.get("title") and _year(item) == year:
                    found.setdefault(item["DOI"].lower(), item)
    return list(found.values())


def sizes(year: int, groups: dict[str, list[str]], ask, batch: int = 40) -> dict[str, int]:
    """How many articles of ``year`` each journal has, without fetching them."""
    wanted = sorted({issn for group in groups.values() for issn in group})
    counts: dict[str, int] = {}
    for start in range(0, len(wanted), batch):
        part = wanted[start:start + batch]
        filters = ["type:journal-article", f"from-pub-date:{year}-01-01", f"until-pub-date:{year}-12-31", *(f"issn:{issn}" for issn in part)]
        answer = ask({"filter": ",".join(filters), "rows": "0", "facet": "issn:*"})["message"]
        for url, number in answer.get("facets", {}).get("issn", {}).get("values", {}).items():
            counts[url.rsplit("/", 1)[-1].upper()] = number
    return {journal: max([counts.get(issn, 0) for issn in group] or [0]) for journal, group in groups.items()}


def _text(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", html.unescape(value)).split())


def publication(item: dict) -> Publication:
    """A Crossref article in the shape of a VABB publication, for the same model and the same output."""
    people = [(_text(a.get("family") or a.get("name") or ""), _text(a.get("given") or "")) for a in item.get("author") or []]
    people = [(family, given) for family, given in people if family]
    title = _text(" ".join(item["title"][:1])) or "?"
    subtitle = _text(" ".join(item.get("subtitle") or [])[:300])
    if subtitle and subtitle.lower() not in title.lower():
        title = f"{title.rstrip('. ')}. {subtitle}"
    return Publication(
        id=item["DOI"].lower(), title=title, type="article", year=_year(item), pages=item.get("page"),
        families=[family for family, _ in people], names=[f"{family} ({given})" if given else family for family, given in people],
        container=_text((item.get("container-title") or [""])[0]), doi=item["DOI"].lower(), issn=list(item.get("ISSN") or []),
        url=f"https://doi.org/{item['DOI']}", volume=item.get("volume") or "", issue=item.get("issue") or "",
    )


def _extent(pub: Publication) -> int | None:
    numbers = [int(number) for number in re.findall(r"\d+", pub.pages or "")]
    return numbers[1] - numbers[0] + 1 if len(numbers) == 2 and 0 <= numbers[1] - numbers[0] < 500 else None


def tokens(pub: Publication) -> list[str]:
    """What tells a research article from the notices and surveys Crossref files as articles."""
    extent = _extent(pub)
    length = "unknown" if extent is None else "short" if extent <= 3 else "middle" if extent <= 7 else "long"
    return [f"extent_{length}", "authors_none" if not pub.families else "authors_some"]


FRONT = re.compile(r"(front matter|back matter|appendix|erratum|table of contents)\b|corrigend", re.I)
REVIEW = re.compile(r"(recensie|comptes? rendus?|signalement|book review|review of|boekbespreking)\b", re.I)
# A title that is a book's: "Janna Coomans, Community, Urban Health …", or one with its editors, its price or its size.
_BOOK = re.compile(
    r"(?:[A-ZÀ-Þ][\w.’'-]*\.? ){1,3}(?:(?:van|de|der|den|le|la|du|von|d’|Van|De|Vanden|Vander) ?)*[A-ZÀ-Þ][\w’'-]+"
    r"(?: (?:and|en|et|und|&) [^,]{4,40})?(?: ?\((?:eds?|red|dir|coord|reds)\.?\))?, (?=[A-ZÀ-ÞL«“\"‘])")
_EDITED = re.compile(r"\bby [A-Z]\. [A-Z]|\((?:eds?|dir|red)\.\)|\bISBN\b|\b\d{2,4} (?:pp?|blz)\b")


def is_front(pub: Publication) -> bool:
    return bool(FRONT.match(pub.title))


# BMGN files its reviews under the book's title and gives no pages (269 in 2018–2021, none of them in a volume).
_REVIEWS_WITHOUT_PAGES = {"0165-0505", "2211-2898"}


def is_review(pub: Publication) -> bool:
    """A book review, by the start of its title, or by a title that is a book's on at most six pages. The volumes list
    none. Whether they should is a question for the Commission (Mike, 25 Nov 2026), so reviews get a list of their own."""
    if REVIEW.match(pub.title):
        return True
    extent = _extent(pub)
    short = bool(_REVIEWS_WITHOUT_PAGES & set(pub.issn)) if extent is None else extent <= 6
    return short and bool(_BOOK.match(pub.title) or _EDITED.search(pub.title))


def distinct(found: list[tuple[Publication, float]]) -> list[tuple[Publication, float]]:
    """One of the articles Crossref has twice (a French and an English DOI, a chapter of one's own): the same title,
    first author and pages. The same title on other pages is a second part, and stays."""
    kept: dict[tuple, tuple[Publication, float]] = {}
    for pub, value in found:
        kept.setdefault((fold(pub.title), fold(pub.families[0] if pub.families else ""), pub.pages or pub.id), (pub, value))
    return list(kept.values())


def eligible(pub: Publication, by_issn: dict[str, str], seen: dict[str, set[int]]) -> bool:
    """Whether an earlier volume took an article from the journal, so a measured year does not know its own answers."""
    return any(min(seen[journal]) < (pub.year or 0) for journal in {by_issn.get(issn) for issn in pub.issn} if journal in seen)


def listed(records, pubs: dict[str, Publication], volumes) -> dict[str, str]:
    """The articles an entry of these volumes lists, with the entry's id: by the entry's DOI, else matched on title,
    author and year by the rules for a VABB publication."""
    index = Index(pubs)
    found: dict[str, str] = {}
    for record in records:
        if record.role != "entry" or record.bgb_year not in volumes or not record.title:
            continue
        key = (record.doi or "").lower()
        if key not in pubs:
            result, pub = match(record, index)
            key = pub.id if pub and result.accepted else ""
        if key:
            found.setdefault(key, record.id)
    return found


def ask_crossref(cache: Path):
    return lambda params: fetch(params, cache)
