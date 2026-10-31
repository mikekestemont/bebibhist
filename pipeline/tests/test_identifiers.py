"""Scoring of Crossref candidates, without the network."""

from bhb.identifiers import accept, best_match, query_params, same_name, score, title_language
from bhb.model import Host, Person, Publisher, Record


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


def test_one_name_in_two_spellings_is_the_same_author():
    for ours, theirs in (("Vanbruaene", "Van Bruaene"), ("Van Dyck", "Dijck"), ("Godderis", "Goddeeris"),
                         ("Quaeghebeur", "Quaghebeur"), ("Van Ysacker", "Vanysacker"), ("Vandewinkel", "Vande Winkel")):
        assert same_name(ours, theirs), (ours, theirs)
    for ours, theirs in (("Haquin", "Lamberigts"), ("Spellers", "Van Linthout"), ("Mommaers", "Vanneste")):
        assert not same_name(ours, theirs), (ours, theirs)


def test_an_edited_volume_is_compared_by_its_editor():
    record = _record(family="Bousmar")
    record.persons[0].role = "editor"
    item = _item(family="Bousmar")
    assert score(record, item)["author"] is True


def test_the_same_book_in_another_language_is_not_a_match():
    assert title_language("Hieronymus Cock: De renaissance in prent van de Lage Landen") == "nl"
    assert title_language("Hieronymus Cock. The Renaissance in Print of the Low Countries") == "en"
    assert title_language("Hieronymus Cock") is None
    record = _record(title="Hieronymus Cock: De renaissance in prent van de Lage Landen", pages=None)
    item = _item(title="Hieronymus Cock. The Renaissance in Print of the Low Countries", page=None)
    assert score(record, item)["language"] is False and not accept(score(record, item), 60, 90, 85)


def test_a_short_title_without_a_known_author_is_refused():
    record = _record(title="Conclusion", family="Maerten", pages="221-226")
    item = _item(title="Conclusion", page="301-310")
    item["author"] = []
    item["container-title"] = ["Pierre Giot, un capitaine marin arlésien « dans la tourmente »"]
    record.host.title = "Mons dans la tourmente"
    assert not accept(score(record, item), len("Conclusion"))


def test_a_book_is_not_matched_to_a_review_of_it():
    record = _record(title="Medieval Merchant Venturers. Collected studies", family="Carus-Wilson", year=1954)
    record.host = None
    record.publisher = Publisher(place="Londres", name="Methuen")
    item = _item(title="Medieval Merchant Venturers: Collected Studies.", family="Carus-Wilson", year=1955, page="374")
    item["type"] = "journal-article"
    item["container-title"] = ["Economica"]
    assert not accept(score(record, item), 60)


def test_vabb_dois_are_normalised():
    from bhb.vabb import normalise_doi

    assert normalise_doi("doi:10.1093/jsh/shs092.") == "10.1093/jsh/shs092"
    assert normalise_doi("http://dx.doi.org/10.1080/14664208.2016.1243883") == "10.1080/14664208.2016.1243883"
    assert normalise_doi("n/a") is None


def test_apply_writes_crossref_first_and_recovers_a_missing_journal(tmp_path, monkeypatch):
    import csv

    import bhb.identifiers as identifiers
    from bhb.model import Provenance

    first = _record()
    first.host.title, first.host.id = "[host record not exported]", "bhb:vs-9"
    sibling = Record(id="bhb:vs-2", source="vsmart", bgb_year=2017, type="article", title="Een ander artikel", year=2017,
                     persons=[Person(family="Rys")], host=Host(title="[host record not exported]", id="bhb:vs-9"), provenance=Provenance())
    item = _item()
    item["ISSN"] = ["07724764"]
    monkeypatch.setattr(identifiers, "fetch", lambda params, cache: {"message": {"items": [item]}})
    columns = ["id", "accepted", "doi", "isbn", "issn", "their_container"]
    with (tmp_path / "vsmart.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, columns)
        writer.writeheader()
        writer.writerow({"id": first.id, "accepted": "1", "doi": item["DOI"], "isbn": "", "issn": "", "their_container": ""})
    with (tmp_path / "vabb.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, columns)
        writer.writeheader()
        writer.writerow({"id": first.id, "accepted": "1", "doi": "doi:10.9999/other.", "isbn": "", "issn": "0772-4764", "their_container": "Ghendtsche Tydinghen"})
    identifiers.apply_identifiers([first, sibling], tmp_path, tmp_path)
    assert first.doi == item["DOI"].lower() and first.identifiers_from == {"doi": "crossref", "issn": "crossref"}
    assert first.issn == ["0772-4764"]
    assert sibling.host.title == "Ghendtsche Tydinghen" and "host-title-matched" in sibling.provenance.flags
    assert sibling.doi is None
