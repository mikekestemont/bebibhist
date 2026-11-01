"""Candidates for the most recent years from the VABB-SHW (the pilot of `docs/DECISIONS.md`, 1 Nov 2026).

The Flemish Academic Bibliography lists the publications of researchers at Flemish universities, also for 2018–2023,
which the bibliography does not have yet. A relevance model says which of them the bibliography would include. It
learns from the years both cover: a VABB publication matched to an entry (``build/identifiers/vabb.csv``) is one
the bibliography took, the others are ones it did not (or that the matcher missed, which makes the measured
precision a lower bound). It is a logistic regression on the title's words, the VABB disciplines, the journal or
book, the type and the language; no language model.

The model is trained on earlier years and measured on later ones it has not seen, then applied to 2018–2023. The
candidates are machine-proposed and are not entries of the bibliography.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from bhb.journals import spelling_key
from bhb.textutil import fold

TRAIN_YEARS = range(2003, 2013)
TEST_YEARS = range(2013, 2015)
CANDIDATE_YEARS = range(2018, 2024)


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


def features(pub, known: Known | None = None) -> str:
    """The publication as one text of tokens: title words, and marked tokens for discipline, journal, type, language
    and what the bibliography already knows, so a single TF-IDF vectoriser handles all."""
    tokens = [word for word in fold(pub.title).split() if len(word) >= 3]
    tokens += known.tokens(pub) if known else []
    tokens += [f"disc_{fold(label).replace(' ', '_')}" for label in pub.disciplines] or ["disc_none"]
    tokens += [f"issn_{number.replace('-', '')}" for number in pub.issn]
    tokens += [f"cont_{word}" for word in fold(pub.container).split() if len(word) >= 4]
    tokens += [f"type_{pub.type}", f"lang_{pub.language or 'none'}"]
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
    rows: list[tuple[float, float, float, int]]  # threshold, precision, recall, proposed


def train_and_measure(pubs: dict, positive: set[str], known: Known | None = None):
    """Fit on ``TRAIN_YEARS``, measure on ``TEST_YEARS``, then refit on both for the candidates."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score
    from sklearn.pipeline import make_pipeline

    def split(years):
        chosen = [pub for pub in pubs.values() if pub.year in years]
        return chosen, [features(pub, known) for pub in chosen], [int(pub.id in positive) for pub in chosen]

    def model():
        return make_pipeline(TfidfVectorizer(token_pattern=r"\S+", min_df=2, sublinear_tf=True, ngram_range=(1, 1)),
                             LogisticRegression(C=4.0, max_iter=2000, class_weight="balanced"))

    _, x_train, y_train = split(TRAIN_YEARS)
    test_pubs, x_test, y_test = split(TEST_YEARS)
    fitted = model().fit(x_train, y_train)
    scores = fitted.predict_proba(x_test)[:, 1]
    rows = []
    for threshold in (0.5, 0.7, 0.8, 0.9, 0.95):
        proposed = [label for score, label in zip(scores, y_test) if score >= threshold]
        hits = sum(proposed)
        rows.append((threshold, hits / len(proposed) if proposed else 0.0, hits / max(1, sum(y_test)), len(proposed)))
    evaluation = Evaluation(len(y_train), sum(y_train), len(y_test), sum(y_test), average_precision_score(y_test, scores), rows)
    final = model().fit(x_train + x_test, y_train + y_test)
    return evaluation, final, list(zip(test_pubs, scores, y_test))


def candidates(pubs: dict, model, threshold: float, known: Known | None = None) -> list[tuple[object, float]]:
    chosen = [pub for pub in pubs.values() if pub.year in CANDIDATE_YEARS]
    scores = model.predict_proba([features(pub, known) for pub in chosen])[:, 1]
    return sorted(((pub, float(score)) for pub, score in zip(chosen, scores) if score >= threshold), key=lambda pair: -pair[1])
