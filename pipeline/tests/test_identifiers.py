"""Scoring of Crossref candidates, without the network."""

from bhb.identifiers import accept, best_match, query_params, score
from bhb.model import Host, Person, Record


def _record(title="Criminaliteit in Gent in de vorige eeuw", subtitle=None, family="Rys", pages="191-197", year=2017):
    return Record(
        id="bhb:vs-1", source="vsmart", bgb_year=2017, type="article", title=title, subtitle=subtitle, year=year,
        persons=[Person(family=family)], host=Host(title="Ghendtsche Tydinghen", pages=pages),
    )


def _item(title="Criminaliteit in Gent in de vorige eeuw.", family="Rys", page="191-197", year=2017, doi="10.21825/gt.v46i3.16912"):
    return {
        "DOI": doi, "title": [title], "author": [{"family": family, "given": "C."}],
        "container-title": ["Ghendtsche Tydinghen"], "issued": {"date-parts": [[year, 5, 1]]}, "page": page,
    }


def test_the_same_article_is_accepted():
    features = score(_record(), _item())
    assert features["title"] >= 95 and features["author"] and features["year"] and features["page"]
    assert accept(features)


def test_s_n_is_no_author_and_does_not_reject_a_match():
    record = _record(family="s.n.")
    assert score(record, _item())["author"] is None
    assert accept(score(record, _item()))
    assert "s.n." not in query_params(record)["query.bibliographic"]


def test_an_ocr_error_in_the_title_still_matches_when_everything_else_agrees():
    record = _record(title="Hildegard von Bingen en de Seivias")
    item = _item(title="Hildegard von Bingen en de Scivias")
    assert accept(score(record, item))
    assert best_match(record, {"message": {"items": [item]}}).their_title == "Hildegard von Bingen en de Scivias"


def test_a_different_article_in_the_same_journal_is_rejected():
    item = _item(title="De Gentse bisschop Antoon Triest op bezoek", family="Verbeke", page="12-30")
    assert not accept(score(_record(), item))


def test_a_same_title_by_another_author_is_rejected():
    assert not accept(score(_record(), _item(family="Janssens")))


def test_a_series_name_for_the_journal_does_not_reject_a_match():
    item = _item()
    item["container-title"] = ["Publications du Centre Européen d'Études Bourguignonnes"]
    assert accept(score(_record(), item), 40)


def test_a_short_title_needs_the_journal_or_the_page():
    record = _record(title="Belgium", pages=None)
    item = _item(title="Belgium", page=None)
    item["container-title"] = ["Imagology"]
    assert not accept(score(record, item), len("Belgium"))
