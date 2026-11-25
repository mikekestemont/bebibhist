"""Candidates for the years still to be collected, from the VABB-SHW (`docs/IMPLEMENTATION_PLAN.md` §4i).

The Flemish Academic Bibliography lists the publications of researchers at Flemish universities, also of years the
editor has not collected yet: from 2024 on. A relevance model says which of them the bibliography would include. It
learns from the years both cover: a VABB publication matched to an entry (``build/identifiers/vabb.csv``) is one
the bibliography took, the others are ones it did not (or that the matcher missed, which makes the measured
precision a lower bound). It is a logistic regression on the title's words, the VABB disciplines, the journal or
book, the type, the language and what the bibliography already knows (an author, a journal or a series from
earlier volumes); no language model.

The model is measured on 2018–2021, the editor's four most recent complete volumes, trained on 2000–2017; it is then
trained on all of 2000–2021 and applied to the years after. The candidates are machine-proposed and are not entries of
the bibliography: they are for review in a Zotero inbox, once the Commission's Zotero library is set up, and neither
the site nor the data release carries them.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from bhb.journals import spelling_key
from bhb.textutil import fold

TEST_YEARS = range(2018, 2022)
TRAIN_YEARS = range(2000, TEST_YEARS.start)
CANDIDATE_YEARS = range(TEST_YEARS.stop, 2025)
# Two groups for the editor: A, where about three in four are right, and B, where about two in five are (measured on
# 2018–2021 and a sample read by Claude, 25 Nov 2026: `docs/IMPLEMENTATION_PLAN.md` §4i). Below B it is mostly noise.
GROUP_A = 0.8
THRESHOLD = 0.5


@dataclass
class Known:
    """When the bibliography first listed an author (family name), a journal (spelling or ISSN) and a book series,
    by year of the volume: a publication counts as known only through earlier volumes, so the measured years do not
    see their own answers."""
    authors: dict[str, list[int]]
    journals: dict[str, int]
    series: dict[str, int]
    # Every ISSN of a journal (print and online) to the number that names it: one shared number identifies it.
    issn_groups: dict[str, str]

    def tokens(self, pub) -> list[str]:
        year = pub.year or 9999
        earlier = [sum(1 for seen in self.authors.get(fold(family), []) if seen < year) for family in pub.families + pub.editors]
        tokens = []
        if any(earlier):
            tokens.append("known_author")
        if any(n >= 3 for n in earlier):
            tokens.append("known_author_often")
        keys = [spelling_key(pub.container)] if pub.container else []
        keys += [f"issn:{self.issn_groups.get(number, number)}" for number in pub.issn]
        if any(self.journals.get(key, 9999) < year for key in keys):
            tokens.append("known_journal")
        if pub.series and self.series.get(spelling_key(pub.series), 9999) < year:
            tokens.append("known_series")
        return tokens


def known_from(records, journal_list: Path | None = None) -> Known:
    from collections import defaultdict

    groups: dict[str, str] = {}
    if journal_list and journal_list.exists():
        with journal_list.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                for number in filter(None, row["issn"].split("|")):
                    groups[number] = row["id"].removeprefix("issn:")

    authors: dict[str, list[int]] = defaultdict(list)
    journals: dict[str, int] = {}
    series: dict[str, int] = {}

    def first(table: dict[str, int], key: str, year: int) -> None:
        if key and year < table.get(key, 9999):
            table[key] = year

    for record in records:
        if record.role != "entry" or not record.bgb_year:
            continue
        for person in record.persons:
            authors[fold(person.family)].append(record.bgb_year)
        if record.host and record.host.title and not record.host.title.startswith("["):
            first(journals, spelling_key(record.host.title), record.bgb_year)
            for number in record.issn:
                first(journals, f"issn:{groups.get(number, number)}", record.bgb_year)
        if record.series and record.series.title:
            first(series, spelling_key(record.series.title), record.bgb_year)
    return Known(dict(authors), journals, series, groups)


def features(pub, known: Known | None = None, extra=None) -> str:
    """The publication as one text of tokens: title words, and marked tokens for discipline, journal, type, language
    and what the bibliography already knows, so a single TF-IDF vectoriser handles all. ``extra`` gives a source's own tokens."""
    tokens = [word for word in fold(pub.title).split() if len(word) >= 3]
    tokens += known.tokens(pub) if known else []
    tokens += [f"disc_{fold(label).replace(' ', '_')}" for label in pub.disciplines] or ["disc_none"]
    tokens += [f"issn_{number.replace('-', '')}" for number in pub.issn]
    tokens += [f"cont_{word}" for word in fold(pub.container).split() if len(word) >= 4]
    tokens += [f"type_{pub.type}", f"lang_{pub.language or 'none'}"]
    tokens += extra(pub) if extra else []
    return " ".join(tokens)


def labels(path: Path) -> set[str]:
    """The VABB publications matched to an entry of the bibliography."""
    with path.open(encoding="utf-8") as handle:
        return {row["vabb_id"] for row in csv.DictReader(handle) if row["accepted"] == "1"}


@dataclass
class Evaluation:
    train: int
    train_positive: int
    test: int
    test_positive: int
    average_precision: float
    rows: list[tuple[float, float, float, float, float]]  # threshold, precision, recall, proposed a year, right a year


def _split(pubs: dict, positive: set[str], known: Known | None, years, extra=None):
    chosen = [pub for pub in pubs.values() if pub.year in years]
    return chosen, [features(pub, known, extra) for pub in chosen], [int(pub.id in positive) for pub in chosen]


def _fit(texts: list[str], answers: list[int]):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    return make_pipeline(TfidfVectorizer(token_pattern=r"\S+", min_df=2, sublinear_tf=True, ngram_range=(1, 1)),
                         LogisticRegression(C=4.0, max_iter=2000, class_weight="balanced")).fit(texts, answers)


def measure(pubs: dict, positive: set[str], known: Known | None = None, train_years=TRAIN_YEARS, test_years=TEST_YEARS, extra=None,
            thresholds=(0.3, 0.5, 0.7, 0.8, 0.9, 0.95)):
    """Fit on ``train_years`` and measure on ``test_years``: how the model does on volumes it has not seen. Returns the
    evaluation and the measured publications with their score and answer."""
    from sklearn.metrics import average_precision_score

    _, x_train, y_train = _split(pubs, positive, known, train_years, extra)
    test_pubs, x_test, y_test = _split(pubs, positive, known, test_years, extra)
    scores = _fit(x_train, y_train).predict_proba(x_test)[:, 1]
    rows = []
    for threshold in thresholds:
        proposed = [label for score, label in zip(scores, y_test) if score >= threshold]
        hits = sum(proposed)
        rows.append((threshold, hits / len(proposed) if proposed else 0.0, hits / max(1, sum(y_test)),
                     len(proposed) / len(test_years), hits / len(test_years)))
    evaluation = Evaluation(len(y_train), sum(y_train), len(y_test), sum(y_test), average_precision_score(y_test, scores), rows)
    return evaluation, list(zip(test_pubs, scores, y_test))


def train(pubs: dict, positive: set[str], known: Known | None = None, years=frozenset(TRAIN_YEARS) | frozenset(TEST_YEARS), extra=None):
    """The model for the years to come, fitted on every year the bibliography covers."""
    _, texts, answers = _split(pubs, positive, known, years, extra)
    return _fit(texts, answers)


def candidates(pubs: dict, model, threshold: float, known: Known | None = None, listed: frozenset[str] = frozenset(),
               years=CANDIDATE_YEARS, extra=None) -> list[tuple[object, float]]:
    """The publications of ``years`` scoring at least ``threshold``, best first; those already matched to an entry
    (``listed``: a volume can hold a publication of the next year) are left out."""
    chosen = [pub for pub in pubs.values() if pub.year in years and pub.id not in listed]
    if not chosen:
        return []
    scores = model.predict_proba([features(pub, known, extra) for pub in chosen])[:, 1]
    return sorted(((pub, float(score)) for pub, score in zip(chosen, scores) if score >= threshold), key=lambda pair: -pair[1])


SOURCE = "VABB-SHW (ECOOM), CC BY 4.0"
# No language is left out (Mike, 25 Nov 2026). These four are the ones to favour: they decide which source is added
# next, not a publication's score. The report counts them first. VABB has three-letter codes, our own reading two.
FAVOURED = {"dut": "Dutch", "nl": "Dutch", "eng": "English", "en": "English", "fre": "French", "fr": "French", "ger": "German", "de": "German"}


def by_language(rows: list[dict]) -> dict[str, int]:
    """How many candidates there are in each favoured language, and in the others (or without a language) together."""
    counts = {label: 0 for label in [*dict.fromkeys(FAVOURED.values()), "other"]}
    for row in rows:
        counts[FAVOURED.get(row.get("language") or row.get("language_suggested", ""), "other")] += 1
    return counts


# The bibliography knows an author by family name only, so a namesake counts too.
REASONS = {"known_author": "an author's family name in earlier volumes", "known_author_often": "an author's family name at least three times in earlier volumes",
           "known_journal": "journal in earlier volumes", "known_series": "series in earlier volumes"}


def candidate_row(pub, score: float, known: Known | None = None, group_a: float = GROUP_A, source: str = SOURCE) -> dict:
    """A candidate for review, with only what the source gives: every value is the source's; the score, the group and
    the reasons are the model's. The fields map onto a Zotero item (``ris``)."""
    tokens = known.tokens(pub) if known else []
    if "known_author_often" in tokens:
        tokens.remove("known_author")
    row = {
        "id": pub.id,
        "score": round(float(score), 3),
        "group": "A" if score >= group_a else "B",
        "reasons": [REASONS[token] for token in tokens],
        "year": pub.year,
        "type": pub.type,
        "authors": [name for name in pub.names if name],
        "editors": [name for name in pub.editor_names if name],
        "title": pub.title,
        "container": pub.container,
        "series": pub.series,
        "volume": pub.volume,
        "issue": pub.issue,
        "pages": pub.pages,
        "language": pub.language,
        "disciplines": list(pub.disciplines),
        "doi": pub.doi,
        "isbn": list(pub.isbn),
        "issn": list(pub.issn),
        "url": pub.url or f"https://anet.be/record/opacvabbg/{pub.id}/E",
        "source": source,
    }
    return {key: value for key, value in row.items() if value not in (None, "", [])}


RIS_TYPES = {"article": "JOUR", "chapter": "CHAP", "book": "BOOK"}


def _ris_name(name: str) -> str:
    """"Verelst (Karin)" → "Verelst, Karin"."""
    family, _, given = name.partition(" (")
    return f"{family}, {given.rstrip(')')}" if given else family


def ris(row: dict) -> str:
    """A candidate as a RIS record for Zotero's import: the bibliographic fields, its source and group as tags, and
    the score and reasons in a note."""
    article, chapter = row["type"] == "article", row["type"] == "chapter"
    start, _, end = (row.get("pages") or "").partition("-")
    lines = [("TY", RIS_TYPES.get(row["type"], "GEN"))]
    lines += [("AU", _ris_name(name)) for name in row.get("authors", [])]
    lines += [("ED", _ris_name(name)) for name in row.get("editors", [])]
    lines += [("TI", row["title"]), ("PY", row.get("year"))]
    lines += [("T2", row.get("container"))] if article or chapter else []
    lines += [("T3", row.get("series")), ("VL", row.get("volume")), ("IS", row.get("issue")), ("SP", start), ("EP", end), ("LA", row.get("language")), ("DO", row.get("doi"))]
    lines += [("SN", number) for number in (row.get("issn") if article else row.get("isbn")) or []]
    lines += [("UR", row["url"]), ("KW", "source:vabb" if row["source"] == SOURCE else "source:crossref"), ("KW", f"group:{row['group']}"),
              ("KW", "status:to-check"), ("KW", f"kind:{row['kind']}" if row.get("kind") else "")]
    lines += [("N1", f"{row['source']}; model score {row['score']}" + "".join(f"; {reason}" for reason in row.get("reasons", [])))]
    return "".join(f"{tag}  - {' '.join(str(value).split())}\n" for tag, value in lines if value) + "ER  - \n\n"
