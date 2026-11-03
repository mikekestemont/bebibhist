"""Two digitisations compared: typography is no difference, the known word wins."""

from collections import Counter

from bhb.ocr_compare import decide, differences


def test_typography_is_no_difference_and_a_misread_word_is():
    assert differences("d’un ermite du xiiiᵉ s. à Liège-Ouest", "d'un ermite du xiiie s. à Liège Ouest") == []
    assert differences("Het kasteel van Toumai, Biekorf, LXXIV", "Het kasteel van Tournai, Biekorf, LXXIV") == [("Toumai", "Tournai")]
    assert differences("Een heel ander artikel", "Dhondt (J.). Bibliographie de l'Histoire de Belgique") is None


def test_the_reading_known_elsewhere_in_the_bibliography_wins():
    counts = Counter({"tournai": 900, "toumai": 1, "liege": 5000, "luge": 4, "staes": 2, "staeg": 1})
    assert decide("Toumai", "Tournai", counts) == "persee"
    assert decide("Liège", "Lüge", counts) == "straive"
    assert decide("Staes", "Staeg", counts) == "undecided"


def test_an_ocr_fix_is_kept_only_for_a_rare_word_corrected_to_a_known_one():
    from bhb.citations import checked_ocr_fixes

    counts = Counter({"iite": 1, "site": 275, "gent": 6895, "gand": 790, "bull": 3911})
    answer = {"ocr_fixes": [{"printed": "iite", "corrected": "site"}, {"printed": "Gent", "corrected": "Gand"},
                            {"printed": "Bull,", "corrected": "Bull."}]}
    kept = checked_ocr_fixes(answer, "Fysisch kader van het iite van Halle. Gent, Bull, 1967", counts)
    assert kept == [{"printed": "iite", "corrected": "site"}]


def test_abbreviations_old_spellings_and_given_names_are_not_corrected_on_counts_alone():
    from bhb.ocr_compare import Reading, plausible

    text = "Mueller (Harmut). Die Dekanate (arr. de Turnhout), œconomiques. Alired (Alired)."
    names = Counter({"alfred": 40})
    at = lambda word: text.index(word)
    assert not plausible(Reading("Harmut", ["Hannut"], at("Harmut"), at("Harmut") + 6), text, names)
    assert not plausible(Reading("arr", ["an"], at("arr"), at("arr") + 3), text, names)
    assert not plausible(Reading("œconomiques", ["économiques"], at("œcon"), at("œcon") + 11), text, names)
    assert plausible(Reading("Alired", ["Alfred"], text.rindex("Alired"), text.rindex("Alired") + 6), text, names)
