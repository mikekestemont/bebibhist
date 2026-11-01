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

from bhb.textutil import fold

TRAIN_YEARS = range(2003, 2013)
TEST_YEARS = range(2013, 2015)
CANDIDATE_YEARS = range(2018, 2024)


def features(pub) -> str:
    """The publication as one text of tokens: title words, and marked tokens for discipline, journal, type and
    language, so a single TF-IDF vectoriser handles all."""
    tokens = [word for word in fold(pub.title).split() if len(word) >= 3]
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


def train_and_measure(pubs: dict, positive: set[str]):
    """Fit on ``TRAIN_YEARS``, measure on ``TEST_YEARS``, then refit on both for the candidates."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score
    from sklearn.pipeline import make_pipeline

    def split(years):
        chosen = [pub for pub in pubs.values() if pub.year in years]
        return chosen, [features(pub) for pub in chosen], [int(pub.id in positive) for pub in chosen]

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


def candidates(pubs: dict, model, threshold: float) -> list[tuple[object, float]]:
    chosen = [pub for pub in pubs.values() if pub.year in CANDIDATE_YEARS]
    scores = model.predict_proba([features(pub) for pub in chosen])[:, 1]
    return sorted(((pub, float(score)) for pub, score in zip(chosen, scores) if score >= threshold), key=lambda pair: -pair[1])
