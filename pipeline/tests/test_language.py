"""Language of publication from the title: cleaning, the decision rule, bilingual titles and the fallbacks."""

from bhb.language import clean, decide, languages_of, own_words, Reading, segments, suggest, votes
from bhb.model import Host, Record


def test_cleaning_drops_quotations_brackets_numbers_and_roman_numerals_but_not_articles():
    assert clean("Les « Excessus et incontinentiae clericorum » dans l’archidiaconé de Hainaut (1499–1570)") == \
        "Les dans l’archidiaconé de Hainaut"
    assert clean("Le XVIIIᵉ siècle") == "Le siècle"
    assert clean("Die Siegel der Stadt") == "Die Siegel der Stadt"
    assert clean("L’architecture cistercienne") == "L’architecture cistercienne"
    # A title that is all quotation keeps its words.
    assert clean("'Heilig Jaar'") == "'Heilig Jaar'"


def test_names_and_places_are_not_words_of_a_language_but_function_words_are_however_written():
    assert own_words("Félix Van Bever") == 0
    assert own_words("Het Caermersklooster in Gent") == 2
    assert votes("Bibliografie van Bredene") == {"nl": 1}
    # A particle between two names is part of a name.
    assert votes("Patología ocular en la obra de Anton van Dyck") == {}


def test_the_identifier_decides_when_sure_and_function_words_decide_short_titles():
    assert decide([("nl", 0.94), ("en", 0.02)], "De gemeenteschool") == Reading("nl", 0.94, 2, True, 0)
    # Unsure, but its function words point to the language ranked first.
    assert decide([("fr", 0.32), ("da", 0.14)], "Le Fort d’Embourg").language == "fr"
    assert decide([("fr", 0.32), ("da", 0.14)], "Le Fort d’Embourg").sure
    # Names only: no language.
    assert not decide([("nl", 0.2), ("fr", 0.1)], "Damme in").sure


def test_latin_and_rarer_languages_need_more_evidence():
    # Latinate English is not Latin when it has English function words.
    assert decide([("la", 0.71), ("en", 0.2)], "International bibliography of historical demography").sure is False
    assert decide([("la", 0.96), ("en", 0.01)], "Bona et jura monasterii Haffligemensis").language == "la"
    assert decide([("es", 0.86), ("pt", 0.08)], "Describir la guerra. Narrativas de la primera década").language == "es"
    # Spanish barely ahead of Portuguese is not enough.
    assert not decide([("es", 0.54), ("pt", 0.30)], "Una ciudad dentro de la ciudad").sure


def test_segments_split_where_a_title_turns_to_another_language():
    assert segments("Hommes et pouvoirs — Machten en mensen") == ["Hommes et pouvoirs", "Machten en mensen"]
    assert segments("Thijs (W.) en P. L. Tak") == ["Thijs (W.) en P. L. Tak"]


def _strong(language: str) -> Reading:
    return Reading(language, 0.99, 5, True)


def test_a_bilingual_title_gives_both_languages_in_the_order_printed():
    record = Record(id="bhb:1", source="print-straive", bgb_year=1990)
    text = "Bibliographie de l’histoire de Belgique — Bibliografie van de geschiedenis van België"
    parts = segments(text)
    assert languages_of(record, text, "nl", [(parts[0], _strong("fr")), (parts[1], _strong("nl"))]) == ["fr", "nl"]


def test_a_quotation_used_as_a_title_does_not_make_a_publication_bilingual():
    record = Record(id="bhb:1", source="vsmart", bgb_year=2014)
    text = "There's something rotten. De liquidatie van de repressie en het Europese Verdrag tot Bescherming"
    parts = segments(text)
    assert languages_of(record, text, "en", [(parts[0], _strong("en")), (parts[1], _strong("nl"))]) == ["nl"]


class _Fake:
    """Reads a title as the language named after its last word, sure when the title has three words or more."""

    def read(self, texts):
        return [Reading(text.split()[-1], 0.99, len(text.split()), len(text.split()) >= 3) for text in texts]


def test_a_parallel_title_counts_but_the_editors_bracketed_translation_does_not():
    vsmart = Record(id="bhb:vs-1", source="vsmart", bgb_year=2016, title="Verhaeren Verbeeld nl",
                    title_translated="Le Regard de Verhaeren fr")
    printed = Record(id="bhb:1959-1018", source="print-straive", bgb_year=1959, title="De oudste kruisweg nl",
                     title_translated="Le plus ancien chemin fr")
    suggest([vsmart, printed], _Fake())
    assert vsmart.language_suggested == ["nl", "fr"] and "language-bilingual" in vsmart.provenance.flags
    assert printed.language_suggested == ["nl"]


def test_a_title_of_names_takes_its_journal_language_when_the_journal_has_only_one():
    journal = [Record(id=f"bhb:{n}", source="print-straive", bgb_year=1960, type="article", title="Een titel nl",
                      journal_id="t:biekorf") for n in range(10)]
    names = Record(id="bhb:x", source="print-straive", bgb_year=1960, type="article", title="Jan nl",
                   journal_id="t:biekorf")
    loose = Record(id="bhb:y", source="print-straive", bgb_year=1960, type="book", title="Jan nl")
    counts = suggest(journal + [names, loose], _Fake())
    assert names.language_suggested == ["nl"] and "language-from-journal" in names.provenance.flags
    assert loose.language_suggested == []
    assert counts["from journal"] == 1 and counts["none"] == 1


def test_a_chapter_of_names_takes_its_volume_language_when_the_other_chapters_agree():
    host = Host(title="Liège et le Royaume des Pays-Bas", id=None)
    chapters = [Record(id=f"bhb:c{n}", source="print-straive", bgb_year=1982, type="chapter", title="Un titre fr",
                       host=host) for n in range(2)]
    names = Record(id="bhb:c9", source="print-straive", bgb_year=1982, type="chapter", title="Conclusion fr", host=host)
    suggest(chapters + [names], _Fake())
    assert names.language_suggested == ["fr"] and "language-from-volume" in names.provenance.flags


def test_function_words_of_a_rarer_language_outvote_a_narrow_latin_reading():
    # Sébastien, 9 Nov 2026 (bhb:2004-44992): the identifier read this Spanish title as Latin by a hair.
    title = "Interiorisación religiosa y propaganda hagiographica en los Paises Bajos meridionales del siglo XI al siglo XIII"
    reading = decide([("la", 0.56), ("es", 0.43), ("pt", 0.002)], title)
    assert reading.language == "es" and reading.sure
    italian = decide([("la", 0.55), ("it", 0.40)], "Il commercio della lana nella Fiandra degli ultimi secoli")
    assert italian.language == "it" and italian.sure
    # A Spanish title with Spanish function words needs no extra certainty for them.
    assert decide([("es", 0.70), ("pt", 0.10)], "Los tapices de los duques y la corte de Bruselas").sure
