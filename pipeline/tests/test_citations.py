"""The citation pass, without the network: request rules, the answer key and the scoring."""

import json

from bhb import citations
from bhb.citations import (SCHEMA, tidy, combined, copied_values, missing_translations, SYSTEM, Batch, Item, Reply, _number, ask_batch, batch_message, fields_of_answer,
                           fields_of_record, is_collected_volume, key_from_crossref, make_batches, request_body, score)
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


def test_requests_ask_for_full_precision_and_the_strict_schema():
    body = request_body(SYSTEM, "[bhb:1971-16322] Schouteet (A.). De grenzen …", SCHEMA, "deepseek/deepseek-v4.1-flash-1017")
    assert body["provider"]["quantizations"] == ["bf16", "fp16", "fp8"] and body["provider"]["require_parameters"] is True
    assert body["temperature"] == 0 and body["response_format"]["json_schema"]["strict"] is True
    assert "reasoning" not in body and request_body(SYSTEM, "x", SCHEMA, "m", "low")["reasoning"] == {"effort": "low"}


def test_mistral_models_go_to_mistrals_own_eu_endpoint_and_a_named_provider_has_no_fallbacks():
    assert request_body(SYSTEM, "x", SCHEMA, "mistralai/mistral-small-2603")["provider"] == {
        "only": ["mistral/eu"], "allow_fallbacks": False, "require_parameters": True}
    assert request_body(SYSTEM, "x", SCHEMA, "qwen/qwen3.6-35b-a3b", provider="deepinfra/fp8")["provider"]["only"] == ["deepinfra/fp8"]


def _printed(record_id, section, printed="Auteur (A.). Titre. Bruxelles, 1971, 12 p."):
    return Record(id=record_id, source="print-straive", bgb_year=1971, printed=printed, section_path=section)


def test_batches_keep_to_a_section_and_carry_the_entry_before():
    records = [_printed(f"bhb:1971-{n}", ["A"]) for n in range(12)] + [_printed("bhb:1971-99", ["B"])]
    batches = make_batches(records, {}, size=10)
    assert [len(batch.items) for batch in batches] == [10, 2, 1]
    assert batches[0].before is None and batches[1].before == records[9].printed and batches[2].before is None
    assert batches[2].section == "B"
    assert "[bhb:1971-0] Auteur" in batch_message(batches[0]) and "context only" in batch_message(batches[1])


def test_a_collected_volume_with_its_contents_is_a_batch_of_its_own():
    volume = "Nieuw licht op Leopold I. " + "; ".join(f"Auteur{n} (A.). Bijdrage {n}, p. {n * 10}–{n * 10 + 9}" for n in range(1, 6)) + " " + "x" * 300
    assert is_collected_volume(volume)
    records = [_printed("bhb:1997-1", ["A"]), _printed("bhb:1997-2", ["A"], volume), _printed("bhb:1997-3", ["A"])]
    assert [[item.id for item in batch.items] for batch in make_batches(records, {})] == [["bhb:1997-1"], ["bhb:1997-2"], ["bhb:1997-3"]]


def test_a_batch_whose_ids_come_back_wrong_is_asked_again_entry_by_entry(monkeypatch):
    asked = []

    def fake_call(body, cache):
        ids = [line[1:line.index("]")] for line in body["messages"][1]["content"].splitlines() if line.startswith("[")]
        asked.append(ids)
        entries = [{"id": record_id} for record_id in (ids[:1] if len(ids) > 1 else ids)]  # the batch drops an entry
        return Reply({"entries": entries}, "m", "p", 0.001, 10, 10, 0, 0.1, False)

    monkeypatch.setattr(citations, "call", fake_call)
    batch = Batch("A", None, [Item("bhb:1-1", "One."), Item("bhb:1-2", "Two.")])
    answers, replies = ask_batch(batch, "m", None)
    assert sorted(answers) == ["bhb:1-1", "bhb:1-2"] and asked == [["bhb:1-1", "bhb:1-2"], ["bhb:1-1"], ["bhb:1-2"]]
    assert replies[0].error == "ids do not match" and "Two." not in json.dumps(asked[1])


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


def test_a_changed_extent_counts_as_not_copied_and_missing_translations_are_counted():
    printed = "Adolphe Quetelet. Exposition. Bruxelles, Palais des Ac., 1974, xxxi–205 p."
    answer = {"title": "Adolphe Quetelet. Exposition", "extent": "xxxv–205 p.", "persons": [],
              "publishers": [{"place": "Bruxelles", "name": "Palais des Ac."}], "host": None,
              "language": ["fr"], "translations": {"nl": None, "fr": None, "en": "Adolphe Quetelet. Exhibition"}}
    assert copied_values(answer, printed) == (3, 4) and missing_translations(answer) == 1


def test_an_articles_year_in_its_host_counts_and_the_parser_fills_what_the_model_leaves_empty():
    answer = {"title": "De grenzen", "subtitle": None, "persons": [], "year": None,
              "host": {"title": "Hand.", "volume": "CVIII", "issue": None, "year": "1971", "pages": "300–318"}}
    fields = fields_of_answer(answer)
    assert fields["year"] == 1971
    both = combined(fields, fields_of_record(_record()))
    assert both["host"]["issue"] == "3–4" and both["host"]["volume"] == "CVIII" and both["title"] == "De grenzen"


def test_a_bracketed_translation_in_the_subtitle_is_moved_to_title_translated():
    moved = tidy({"title": "De Plaatsnamenstudie in 1957 en 1958", "subtitle": "[La toponymie en 1957 et 1958]", "title_translated": None})
    assert moved["subtitle"] is None and moved["title_translated"] == "La toponymie en 1957 et 1958"
    twice = tidy({"title": "Een kapittel te Aardenburg !", "subtitle": "Un chapitre à A.!", "title_translated": "Un chapitre à A.!"})
    assert twice["subtitle"] is None
    kept = {"title": "Le Château de Clabecq", "subtitle": "le bâtiment, des hommes", "title_translated": None}
    assert tidy(kept) == kept


def test_a_gloss_after_the_host_is_no_translation_and_a_two_digit_year_is_no_issue():
    printed = "Martens (M.). Jachtrecht. [Droit de chasse]. Limburg, XXXI, 52, p. 79–80. [famille]"
    gloss = tidy({"title": "Jachtrecht", "title_translated": "famille", "host": {"title": "Limburg", "issue": None, "year": None}}, printed)
    assert gloss["title_translated"] is None
    kept = tidy({"title": "Jachtrecht", "title_translated": "Droit de chasse", "host": {"title": "Limburg", "issue": None, "year": None}}, printed)
    assert kept["title_translated"] == "Droit de chasse"
    year = tidy({"title": "Jachtrecht", "year": None, "host": {"title": "Limburg", "volume": "XXXI", "issue": "52", "year": None}}, printed, 1952)
    assert year["host"]["issue"] is None and year["year"] == 1952


def test_an_article_keeps_no_publisher():
    assert tidy({"type": "article", "title": "x", "publishers": [{"place": "Verviers", "name": None}]})["publishers"] == []
