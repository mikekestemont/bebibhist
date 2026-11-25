from bhb.vabb import Publication, _person
from bhb.vabb_candidates import CANDIDATE_YEARS, TEST_YEARS, TRAIN_YEARS, Known, by_language, candidate_row, candidates, measure, ris, train


def test_vabb_names_are_written_as_the_bibliography_writes_them():
    assert _person("VERELST, KARIN") == "Verelst (Karin)"
    assert _person("VAN DEN EECKHOUT, PATRICIA") == "Van den Eeckhout (Patricia)"
    assert _person("Gerwen, Van, Jef [1952 - 2002] [a::x]") == "Van Gerwen (Jef)"
    assert _person("JANSEN-SIEBEN, RIA") == "Jansen-Sieben (Ria)"
    assert _person("PLATO") == "Plato"


def test_the_model_is_measured_on_the_complete_volumes_it_never_saw_and_applied_to_the_years_after():
    assert list(TEST_YEARS) == [2018, 2019, 2020, 2021]
    assert max(TRAIN_YEARS) < min(TEST_YEARS)
    assert min(CANDIDATE_YEARS) == 2022 and 2024 in CANDIDATE_YEARS


def test_the_model_measures_on_the_test_years_only_and_then_learns_from_them_too():
    def pub(number, title, year):
        return Publication(id=f"{title}{number}{year}", title=title, type="article", year=year)

    pubs = {p.id: p for year in (2010, 2012, 2019, 2021, 2023) for n in range(4)
            for p in (pub(n, "Brugse begijnen", year), pub(n, "Chinese dynastieen", year))}
    positive = {key for key in pubs if key.startswith("Brugse")}
    evaluation, scored = measure(pubs, positive)
    assert (evaluation.train, evaluation.test) == (16, 16)
    assert {p.year for p, _, _ in scored} == {2019, 2021}
    assert evaluation.average_precision == 1.0
    found = candidates(pubs, train(pubs, positive), 0.5)
    assert {p.id[:6] for p, _ in found} == {"Brugse"} and {p.year for p, _ in found} == {2023}


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
    found = candidates(pubs, _Model(), 0.8, listed=frozenset({"b"}), years=range(2018, 2024))
    assert [pub.id for pub, _ in found] == ["a"]
    assert candidates(pubs, _Model(), 0.8, years={2024}) == []


def test_a_candidate_row_keeps_what_vabb_gives_and_links_to_its_record():
    pub = Publication(id="c:vabb:495316", title="Pioniers in het consumptiekrediet", type="article", year=2020,
                      container="Revue belge d'histoire contemporaine", issn=["0035-0869"], names=["Pannier (Jan)"])
    row = candidate_row(pub, 0.9987)
    assert row["score"] == 0.999
    assert row["authors"] == ["Pannier (Jan)"]
    assert row["url"] == "https://anet.be/record/opacvabbg/c:vabb:495316/E"
    assert "doi" not in row and "editors" not in row  # empty values are left out


def test_a_candidate_says_its_group_and_why_it_is_proposed():
    known = Known({"pannier": [1990, 1995, 2001], "devos": [2010]}, {"revue belge d histoire contemporaine": 1980}, {}, {})
    pub = Publication(id="x", title="Consumptiekrediet", type="article", year=2024, container="Revue belge d'histoire contemporaine",
                      families=["Pannier"], names=["Pannier (Jan)"])
    row = candidate_row(pub, 0.91, known)
    assert row["group"] == "A"
    assert row["reasons"] == ["an author's family name at least three times in earlier volumes", "journal in earlier volumes"]
    assert candidate_row(pub, 0.6, known)["group"] == "B"
    assert "reasons" not in candidate_row(Publication(id="y", title="Iets", type="book", year=2024, families=["Niemand"]), 0.6, known)


def test_a_candidate_becomes_a_ris_record_zotero_can_import():
    pub = Publication(id="c:vabb:1", title="Staging  Mortality", type="chapter", year=2024, container="Medieval Bruges", pages="12-34",
                      names=["Van den Eeckhout (Patricia)"], editor_names=["Brown (Andrew)"], isbn=["978-94-6270-412-1"], issn=["0035-0869"], doi="10.1/x")
    record = ris(candidate_row(pub, 0.83))
    lines = record.splitlines()
    assert lines[0] == "TY  - CHAP" and lines[-2] == "ER  - "
    for line in ("AU  - Van den Eeckhout, Patricia", "ED  - Brown, Andrew", "TI  - Staging Mortality", "T2  - Medieval Bruges", "SP  - 12",
                 "EP  - 34", "DO  - 10.1/x", "SN  - 978-94-6270-412-1", "KW  - source:vabb", "KW  - group:A"):
        assert line in lines
    assert "SN  - 0035-0869" not in lines  # a chapter's number is its book's
    assert "VABB-SHW (ECOOM), CC BY 4.0" in record


def test_no_language_is_left_out_and_four_are_counted_first():
    pubs = {code: Publication(id=code, title="Gent", type="article", year=2024, language=code) for code in ("dut", "eng", "fre", "ger", "ita", "pol", "")}
    found = candidates(pubs, _Model(), 0.8, years={2024})
    assert {pub.language for pub, _ in found} == {"dut", "eng", "fre", "ger", "ita", "pol", ""}
    rows = [candidate_row(pub, score) for pub, score in found]
    assert list(by_language(rows).items()) == [("Dutch", 1), ("English", 1), ("French", 1), ("German", 1), ("other", 3)]
    assert by_language([{"language": "nl"}, {"language": "fr"}, {}])["Dutch"] == 1
