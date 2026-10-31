"""Facet suggestions: scores from neighbours, thresholds per value, and averages per heading."""

import numpy as np

from bhb.facet_suggest import evaluate, label_scores, label_thresholds, pooled


def test_a_value_scores_its_share_of_the_neighbours_similarity():
    scores = label_scores(np.array([0.8, 0.6, 0.6]), [{"religious", "local"}, {"religious"}, {"social"}])
    assert round(scores["religious"], 3) == round(1.4 / 2.0, 3)
    assert round(scores["local"], 3) == 0.4
    assert round(scores["social"], 3) == 0.3


def test_precision_coverage_and_recall_count_every_value():
    point = evaluate([{"a": 0.9, "b": 0.7}, {"a": 0.2}], [{"a"}, {"a"}], 0.6)
    assert (point.predicted, round(point.precision, 2), point.coverage, point.recall) == (2, 0.5, 0.5, 0.5)


def test_each_value_gets_the_lowest_threshold_that_is_right_nine_times_in_ten():
    # "a" is always right; "b" is right only when its score is high.
    scored = [{"a": 0.7, "b": 0.65 if index % 2 else 0.95} for index in range(120)]
    truth = [{"a"} | ({"b"} if not index % 2 else set()) for index in range(120)]
    thresholds = label_thresholds(scored, truth)
    assert thresholds["a"][0] == 0.6
    assert thresholds["b"][0] == 0.7 and thresholds["b"][2] == 1.0


def test_a_heading_averages_its_entries_and_needs_five_of_them():
    ids = [f"r{n}" for n in range(7)]
    groups = {**{f"r{n}": "flandre" for n in range(5)}, "r5": "small", "r6": "small"}
    scores = [{"local": 1.0}, {"local": 0.5, "religious": 0.5}, {"local": 1.0}, {"religious": 1.0}, {"local": 1.0}, {"x": 1.0}, {"x": 1.0}]
    means = pooled(ids, scores, groups)
    assert set(means) == {"flandre"}
    assert round(means["flandre"]["local"], 2) == 0.7 and round(means["flandre"]["religious"], 2) == 0.3
