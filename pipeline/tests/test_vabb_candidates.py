from bhb.vabb import Publication, _person
from bhb.vabb_candidates import CANDIDATE_YEARS, TEST_YEARS, TRAIN_YEARS, candidates, candidate_row


def test_vabb_names_are_written_as_the_bibliography_writes_them():
    assert _person("VERELST, KARIN") == "Verelst (Karin)"
    assert _person("VAN DEN EECKHOUT, PATRICIA") == "Van den Eeckhout (Patricia)"
    assert _person("Gerwen, Van, Jef [1952 - 2002] [a::x]") == "Van Gerwen (Jef)"
    assert _person("JANSEN-SIEBEN, RIA") == "Jansen-Sieben (Ria)"
    assert _person("PLATO") == "Plato"


def test_the_model_is_measured_on_years_the_print_covers_completely_and_never_trained_on_them():
    assert list(TEST_YEARS) == [2006, 2007, 2008]
    assert not set(TEST_YEARS) & set(TRAIN_YEARS)
    assert min(TRAIN_YEARS) == 2000 and max(TRAIN_YEARS) == 2017
    assert not set(CANDIDATE_YEARS) & set(TRAIN_YEARS)


class _Model:
    """Scores a publication by the place its title names, for the test."""

    SCORES = {"brugge": 0.95, "gent": 0.99, "leuven": 0.40, "antwerpen": 0.97}

    def predict_proba(self, texts):
        import numpy as np

        scores = [next(self.SCORES[word] for word in text.split() if word in self.SCORES) for text in texts]
        return np.array([[1 - score, score] for score in scores])


def test_candidates_leave_out_what_the_bibliography_already_lists_and_what_scores_low():
    pubs = {
        "a": Publication(id="a", title="Brugge", type="article", year=2019),
        "b": Publication(id="b", title="Gent", type="article", year=2020),  # matched to an entry already
        "c": Publication(id="c", title="Leuven", type="article", year=2021),
        "d": Publication(id="d", title="Antwerpen", type="article", year=2016),  # not a candidate year
    }
    found = candidates(pubs, _Model(), 0.8, listed=frozenset({"b"}))
    assert [pub.id for pub, _ in found] == ["a"]


def test_a_candidate_row_keeps_what_vabb_gives_and_links_to_its_record():
    pub = Publication(id="c:vabb:495316", title="Pioniers in het consumptiekrediet", type="article", year=2020,
                      container="Revue belge d'histoire contemporaine", issn=["0035-0869"], names=["Pannier (Jan)"])
    row = candidate_row(pub, 0.9987)
    assert row["score"] == 0.999
    assert row["authors"] == ["Pannier (Jan)"]
    assert row["url"] == "https://anet.be/record/opacvabbg/c:vabb:495316/E"
    assert "doi" not in row and "editors" not in row  # empty values are left out
