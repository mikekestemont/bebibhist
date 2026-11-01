"""Scoring of Crossref candidates, without the network."""

from bhb.identifiers import accept, best_match, numbers_agree, query_params, same_name, score, title_language
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
    monkeypatch.setattr(identifiers, "_cached", lambda params, cache: {"message": {"items": [item]}})
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


def test_a_printed_article_is_looked_for_in_its_journal_first():
    record = _record()
    record.source, record.journal_id = "print-straive", "issn:0772-4764"
    assert query_params(record, in_journal=True)["filter"].endswith(",issn:0772-4764")
    assert "issn" not in query_params(record)["filter"]
    item = _item()
    item["container-title"] = ["Ghendtsche Tydinghen. Tijdschrift"]
    item["ISSN"] = ["0772-4764"]
    record.host.title = "Ghendtsche Tyd."
    assert score(record, item)["container"] == 100.0


def test_ocr_proposals_keep_misreadings_and_skip_plurals_and_conventions():
    from bhb.identifiers import word_differences

    assert word_differences("Een kleurijke geschiedenis van Gent", "Een kleurrijke geschiedenis van Gent") == [("kleurijke", "kleurrijke")]
    assert word_differences("Early modern painting in Antwerp", "Early modern paintings in Antwerp") == []
    assert word_differences("The Centre of Bruges", "The Center of Bruges") == []


def test_free_to_read_comes_from_openalex_or_a_persee_doi(tmp_path, monkeypatch):
    import io
    import json as json_
    import urllib.request

    from bhb.identifiers import open_access

    persee, open_, closed, bronze, green = _record(), _record(), _record(), _record(), _record()
    persee.doi, open_.doi, closed.doi = "10.3406/rbph.1955.1972", "10.21825/br.v22i4.15874", "10.1484/j.arihs.5.101852"
    bronze.doi, green.doi = "10.1484/j.rhe.3.232", "10.1017/s0000000000000001"
    answer = {"results": [{"doi": "https://doi.org/10.21825/br.v22i4.15874", "open_access": {"is_oa": True, "oa_status": "bronze"}},
                          {"doi": "https://doi.org/10.1484/j.arihs.5.101852", "open_access": {"is_oa": False, "oa_status": "closed"}},
                          {"doi": "https://doi.org/10.3406/rbph.1955.1972", "open_access": {"is_oa": False, "oa_status": "closed"}},
                          # Free on Brepols' page once, behind the paywall since; a repository copy is not at the DOI.
                          {"doi": "https://doi.org/10.1484/j.rhe.3.232", "open_access": {"is_oa": True, "oa_status": "bronze"}},
                          {"doi": "https://doi.org/10.1017/s0000000000000001", "open_access": {"is_oa": True, "oa_status": "green"}}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=60: io.BytesIO(json_.dumps(answer).encode()))
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    open_access([persee, open_, closed, bronze, green], tmp_path)
    assert persee.free_to_read and persee.identifiers_from["free"] == "persee"
    assert open_.free_to_read and open_.identifiers_from["free"] == "openalex"
    assert closed.free_to_read is None and bronze.free_to_read is None and green.free_to_read is None


def test_open_library_takes_only_a_work_with_one_edition():
    from bhb.openlibrary import score

    record = _record(title="Histoire des Belges et de la Belgique", family="Dumont", pages=None, year=2002)
    record.type, record.host = "book", None
    one = {"key": "/works/OL1W", "title": "Histoire des Belges et de la Belgique", "author_name": ["Georges-Henri Dumont"],
           "publish_year": [2002], "edition_count": 1, "isbn": ["2711744310", "9782711744312"]}
    assert score(record, one).accepted and score(record, one).isbn == ["2711744310", "9782711744312"]
    several = dict(one, edition_count=3, isbn=["2711744310", "9782711744312", "9782804170707"])
    assert not score(record, several).accepted
    other_year = dict(one, publish_year=[1977])
    assert not score(record, other_year).accepted


def test_another_instalment_of_a_yearly_survey_is_not_a_match():
    assert numbers_agree("la philologie wallonne en 1955", "la philologie wallonne en 1964") is False
    assert numbers_agree("ernest mandel in resistance", "ernest mandel in resistance 1940 1945") is True
    assert numbers_agree("pro en contra vesalius", "pro en contra vesalius") is None
    assert numbers_agree("antwerp art after iconoclasm 1566-1585", "antwerp art after iconoclasm 15661585") is True
    record = _record(title="La philologie wallonne en 1955", pages=None)
    item = _item(title="La philologie wallonne en 1964", page=None)
    assert not accept(score(record, item))
    misprint = _record(title="Un Liégeois au siège de Rhodes de 1552")
    assert accept(score(misprint, _item(title="Un Liégeois au siège de Rhodes de 1522")))


def test_a_book_keeps_its_place_in_the_open_library_run_after_an_apply():
    from bhb.openlibrary import books

    looked_up = Record(id="bhb:1", source="print-straive", bgb_year=1980, type="book", title="Een boek", year=1980,
                       isbn=["9789000000001"], identifiers_from={"isbn": "openlibrary"})
    from_vabb = Record(id="bhb:2", source="vsmart", bgb_year=2010, type="book", title="Een ander boek", year=2010,
                       isbn=["9789000000002"], identifiers_from={"isbn": "vabb"})
    assert [record.id for record in books([looked_up, from_vabb])] == ["bhb:1"]


def test_the_plain_answer_is_used_when_the_journal_holds_no_match(monkeypatch):
    import bhb.identifiers as identifiers

    record = _record()
    record.source, record.journal_id = "print-straive", "issn:0772-4764"
    wrong = _item(title="Een heel ander artikel over iets anders", doi="10.1/wrong")
    right = _item()
    answers = {True: {"message": {"items": [wrong]}}, False: {"message": {"items": [right, wrong]}}}
    monkeypatch.setattr(identifiers, "fetch", lambda params, cache: answers["issn:" in params["filter"]])
    found = identifiers.candidates(record, None)["message"]["items"]
    assert [item["DOI"] for item in found] == ["10.1/wrong", right["DOI"]]
    assert best_match(record, {"message": {"items": found}}).accepted


def test_a_journal_is_looked_up_under_each_of_its_numbers(monkeypatch):
    import bhb.identifiers as identifiers

    record = _record()
    record.source, record.journal_id = "print-straive", "issn:0770-0822"
    monkeypatch.setattr(identifiers, "_journal_groups", lambda path: {"issn:0770-0822": ["0770-0822", "0774-286X"]})
    asked = []
    monkeypatch.setattr(identifiers, "_cached", lambda params, cache: asked.append(params["filter"]) or None)
    identifiers.candidates(record, None, offline=True)
    assert [f.rsplit(",", 1)[-1] for f in asked] == ["issn:0770-0822", "issn:0774-286X", "until-pub-date:2018"]


def test_a_year_the_parser_took_from_the_title_still_counts():
    record = _record(title="La philologie Wallonne en", pages=None)
    record.printed = "Legros (E.). La philologie Wallonne en 1953. B. Comm. R. Toponymie et Dialectologie, XXVIII, 54."
    assert not accept(score(record, _item(title="La Philologie wallonne en 1952", page=None)))
    assert accept(score(record, _item(title="La Philologie wallonne en 1953", page=None)))


def test_vabb_finds_an_article_whose_subtitle_it_joins_to_the_title():
    from bhb.vabb import Index, Publication, match

    def pub(pid, title):
        return Publication(id=pid, type="article", title=title, year=2013, families=["Hogenbirk", "Kestemont"],
                           container="Tijdschrift voor Nederlandsche taal- en letterkunde", pages="246-273")

    pubs = {"c:1": pub("c:1", "Het werk van een klerk : een stylometrische verkenning van het auteurschap achter 'Der ystorien bloeme'")}
    pubs.update({f"c:{n}": pub(f"c:{n}", f"Leven en werk {n}") for n in range(2, 9)})
    record = _record(title="Het werk van een klerk", subtitle="Een stylometrische verkenning van het auteurschap achter Der ystorien bloeme",
                     family="Hogenbirk", pages="246-273", year=2013)
    found, _ = match(record, Index(pubs))
    assert found.accepted and found.their_title.startswith("Het werk van een klerk")


def test_an_orcid_comes_from_openalex_and_goes_to_the_same_full_name(tmp_path, monkeypatch):
    import io
    import json as json_
    import urllib.request

    from bhb.identifiers import orcids

    matched = _record(title="Een artikel", family="Deploige", year=2010)
    matched.persons[0].given, matched.doi = "Jeroen", "10.1484/j.rhe.3.232"
    other = _record(title="Een ander artikel", family="Deploige", year=2012)
    other.persons[0].given = "Jeroen"
    older = _record(title="Een oud artikel", family="Deploige", year=1995)
    older.persons[0].given = "Jeroen"
    initials = _record(title="Nog een artikel", family="Deploige", year=2011)
    initials.persons[0].given = "J."
    answer = {"results": [{"doi": "https://doi.org/10.1484/j.rhe.3.232", "authorships": [
        {"raw_author_name": "Bas Diemel", "author": {"orcid": None}},
        {"raw_author_name": "Jeroen Deploige", "author": {"orcid": "https://orcid.org/0000-0001-2345-6789"}}]}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=60: io.BytesIO(json_.dumps(answer).encode()))
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    orcids([matched, other, older, initials], tmp_path)
    assert (matched.persons[0].orcid, matched.persons[0].orcid_from) == ("0000-0001-2345-6789", "openalex")
    assert (other.persons[0].orcid, other.persons[0].orcid_from) == ("0000-0001-2345-6789", "name")
    assert older.persons[0].orcid is None and initials.persons[0].orcid is None


def test_the_registry_gives_an_orcid_only_for_one_belgian_namesake(tmp_path, monkeypatch):
    import io
    import json as json_
    import urllib.request

    from bhb.identifiers import registry_orcid

    rows = [{"orcid-id": "0000-0002-0143-7138", "given-names": "Jeroen", "family-names": "Deploige", "institution-name": ["Ghent University"]},
            {"orcid-id": "0009-0004-4876-2730", "given-names": "Jakob", "family-names": "Deploige", "institution-name": ["Ghent University"]}]
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=60: io.BytesIO(json_.dumps({"expanded-result": rows}).encode()))
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    assert registry_orcid("Deploige", "Jeroen", tmp_path / "a") == "0000-0002-0143-7138"
    rows[1].update({"given-names": "Jeroen"})
    assert registry_orcid("Deploige", "Jeroen", tmp_path / "b") is None
    rows[1].update({"given-names": "Jakob"})
    rows[0].update({"institution-name": ["Utrecht University"]})
    assert registry_orcid("Deploige", "Jeroen", tmp_path / "c") is None
