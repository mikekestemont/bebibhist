from types import SimpleNamespace

from bhb.crossref_candidates import ROWS, distinct, eligible, harvest, is_front, is_review, journals, publication, sizes, tokens
from bhb.vabb_candidates import candidate_row, ris


def _item(doi, year, printed=None, issn="1111-1111", **more):
    item = {"DOI": doi, "title": ["Brugse <i>begijnen</i> &amp; hun tijd"], "issued": {"date-parts": [[year]]}, "ISSN": [issn], **more}
    if printed:
        item["published-print"] = {"date-parts": [[printed]]}
    return item


def test_an_answer_that_does_not_hold_every_article_is_asked_again_in_halves():
    asked = []

    def ask(params):
        batch = [part[5:] for part in params["filter"].split(",") if part.startswith("issn:")]
        asked.append(batch)
        total = 700 * len(batch) if "from-pub-date" in params["filter"] else 0
        items = [_item(f"10.1/{issn}-{n}", 2024, issn=issn) for issn in batch for n in range(2)] if 0 < total <= ROWS else []
        return {"message": {"total-results": total, "items": items}}

    found = harvest(2024, [["1111-1111"], ["2222-2222"]], ask)
    assert asked[:3] == [["1111-1111", "2222-2222"], ["1111-1111"], ["2222-2222"]]
    assert len(found) == 4


def test_one_journal_with_more_articles_than_an_answer_holds_is_read_in_pages():
    def ask(params):
        if "until-print-pub-date" in params["filter"]:
            return {"message": {"total-results": 0, "items": []}}
        start = int(params.get("offset", 0))
        return {"message": {"total-results": 2500, "items": [_item(f"10.1/{n}", 2024) for n in range(start, min(start + ROWS, 2500))]}}

    assert len(harvest(2024, [["1111-1111"]], ask)) == 2500


def test_the_printed_year_decides_and_an_article_online_earlier_is_asked_for_too():
    filters = []

    def ask(params):
        filters.append(params["filter"])
        early = "from-print-pub-date" in params["filter"]
        items = [_item("10.1/early", 2023, printed=2024)] if early else [_item("10.1/now", 2024), _item("10.1/next", 2024, printed=2025)]
        return {"message": {"total-results": len(items), "items": items}}

    assert {item["DOI"] for item in harvest(2024, [["1111-1111"]], ask)} == {"10.1/early", "10.1/now"}
    assert any("until-pub-date:2023-12-31" in text for text in filters)


def test_a_journal_has_the_larger_count_of_its_printed_and_its_online_number():
    def ask(params):
        values = {"http://id.crossref.org/issn/1111-1111": 12, "http://id.crossref.org/issn/2222-222X": 40}
        return {"message": {"facets": {"issn": {"values": values}}}}

    assert sizes(2024, {"a": ["1111-1111", "2222-222X"], "b": ["3333-3333"]}, ask) == {"a": 40, "b": 0}


def test_a_journal_counts_from_the_volume_after_its_first_article():
    records = [SimpleNamespace(role="entry", type="article", journal_id="j", bgb_year=year) for year in (2012, 2019, 2021)]
    seen = journals(records, {"j": ["1111-1111"]})
    assert seen == {"j": {2019, 2021}}  # 2012 is before the years that count
    by_issn = {"1111-1111": "j"}
    assert not eligible(publication(_item("10.1/a", 2019)), by_issn, seen)
    assert eligible(publication(_item("10.1/b", 2020)), by_issn, seen)
    assert not eligible(publication(_item("10.1/c", 2020, issn="9999-9999")), by_issn, seen)


def test_a_crossref_article_keeps_its_volume_and_issue_and_is_credited_to_crossref():
    pub = publication(_item("10.1/A", 2024, author=[{"family": "Brown", "given": "Andrew"}, {"name": "Groep Brugge"}], volume="61", issue="2",
                            page="10-31", subtitle=["1300&#8211;1500"], **{"container-title": ["Urban History"]}))
    assert pub.id == pub.doi == "10.1/a"
    assert pub.title == "Brugse begijnen & hun tijd. 1300–1500"
    assert pub.names == ["Brown (Andrew)", "Groep Brugge"]
    assert tokens(pub) == ["extent_long", "authors_some"]
    record = ris(candidate_row(pub, 0.9, source="Crossref"))
    for line in ("VL  - 61", "IS  - 2", "SP  - 10", "T2  - Urban History", "KW  - source:crossref", "N1  - Crossref; model score 0.9"):
        assert line in record.splitlines()


def test_a_review_of_three_pages_without_an_author_is_told_from_an_article():
    assert tokens(publication(_item("10.1/r", 2024, page="112-114"))) == ["extent_short", "authors_none"]
    assert tokens(publication(_item("10.1/e", 2024))) == ["extent_unknown", "authors_none"]


def test_a_review_is_known_by_its_title_and_goes_to_a_list_of_its_own():
    def pub(title, page=None):
        return publication({**_item("10.1/x", 2024, page=page), "title": [title]})

    assert is_review(pub("Recensie van: Wallonie entre Noirs et Rouges"))
    assert is_review(pub("Compte rendu de Paul Aron, Les Poètes de métier", "1-20"))
    assert is_review(pub("Janna Coomans, Community, Urban Health and Environment in the Late Medieval Low Countries", "120-123"))
    # Without pages a book's title is not enough, except in BMGN, which gives none.
    book = "Pedro Monaville, Students of the World: Global 1968 and Decolonization in the Congo"
    assert not is_review(pub(book))
    assert is_review(publication({**_item("10.1/b", 2024, issn="0165-0505"), "title": [book]}))
    assert not is_review(pub("Vuile Luc, Rare Marus en een gepluimde rekel. Vriend- en vijandschap in tijden van activisme"))
    assert not is_review(pub("Richard Hoesman, Designer and Maker of Stained Glass Windows for Érard de La Marck", "10-30"))
    assert not is_review(pub("Recensies in de Vlaamse pers, 1900–1914", "1-20"))
    assert not is_review(pub("Introduction"))  # the bibliography lists introductions
    assert is_front(pub("Corrigendum to ‘Wages in Ghent’")) and not is_review(pub("Corrigendum to ‘Wages in Ghent’"))
    assert "KW  - kind:review" in ris({**candidate_row(pub("Recensie van: x"), 0.9, source="Crossref"), "kind": "review"}).splitlines()
    assert "kind:" not in ris(candidate_row(pub("Introduction"), 0.9, source="Crossref"))


def test_an_article_with_two_dois_is_proposed_once_and_a_second_part_stays():
    def pub(doi, page):
        return publication(_item(doi, 2024, page=page, author=[{"family": "Brunetti"}]))

    found = [(pub("10.1/fr", "681-703"), 0.9), (pub("10.1/en", "681-703"), 0.8), (pub("10.1/part2", "1-162"), 0.8), (pub("10.1/x", None), 0.8), (pub("10.1/y", None), 0.7)]
    assert [p.id for p, _ in distinct(found)] == ["10.1/fr", "10.1/part2", "10.1/x", "10.1/y"]
