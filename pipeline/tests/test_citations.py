"""The citation pass, without the network: request rules, the answer key and the scoring."""

from bhb.citations import _number, fields_of_answer, fields_of_record, key_from_crossref, request_body, score
from bhb.model import Host, Person, Record

ITEM = {
    "title": ["De grenzen van de Onze-Lieve-Vrouweparochie voor en na 1800"],
    "author": [{"family": "Schouteet", "given": "A."}],
    "container-title": ["Handelingen van het Genootschap voor Geschiedenis te Brugge"],
    "volume": "108", "issue": "3-4", "page": "300-318", "issued": {"date-parts": [[1971]]},
}


def _record():
    return Record(
        id="bhb:1971-16322", source="print-straive", bgb_year=1971, type="article", year=1971,
        title="De grenzen van de Onze-Lieve-Vrouweparochie voor en na 1800", persons=[Person(family="Schouteet", given="A.")],
        host=Host(title="Hand. van de« Société d'Émulation» te Brugge", volume="CVIII", issue="3–4", pages="300–318"),
    )


def test_requests_go_only_to_providers_that_keep_no_data():
    body = request_body("Schouteet (A.). De grenzen …", "deepseek/deepseek-v4.1-flash")
    assert body["provider"]["data_collection"] == "deny" and body["provider"]["zdr"] is True
    assert body["temperature"] == 0 and body["response_format"]["json_schema"]["strict"] is True


def test_roman_volumes_and_dashes_compare_as_numbers():
    assert _number("CVIII") == "108" and _number("t. XLIV") == "44" and _number("3–4") == "3" and _number("jg. 07") == "7"


def test_the_parser_is_scored_on_what_the_key_fixes():
    result = score(fields_of_record(_record()), key_from_crossref(ITEM))
    assert result == {"title": True, "authors": True, "volume": True, "issue": True, "first_page": True, "year": True}


def test_a_model_answer_with_a_wrong_author_and_page_is_scored_as_such():
    answer = {"title": "De grenzen van de Onze-Lieve-Vrouweparochie voor en na 1800", "subtitle": None,
              "persons": [{"family": "Schoutet", "given": "A.", "role": "author"}],
              "host": {"title": "Hand.", "volume": "CVIII", "issue": "3–4", "year": "1971", "pages": "30–318"}, "year": 1971}
    result = score(fields_of_answer(answer), key_from_crossref(ITEM))
    assert result["authors"] is False and result["first_page"] is False and result["volume"] is True
