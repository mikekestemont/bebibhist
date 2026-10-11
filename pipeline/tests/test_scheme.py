from bhb.scheme import (
    SchemeEntry,
    agreement_score,
    code_from_path,
    load_scheme,
    load_theme_map,
    themes_for_code,
    themes_from_label,
)


def test_every_scheme_code_resolves_to_a_theme():
    scheme = load_scheme()
    theme_map = load_theme_map()
    assert scheme
    missing = [code for code in scheme if not themes_for_code(code, theme_map)]
    assert missing == []


def test_local_prefix_is_kept_beside_a_longer_sector():
    theme_map = [("II.C.", "local"), ("II.C.1.b.", "economic")]
    assert themes_for_code("II.C.1.b.1.", theme_map) == ["economic", "local"]


def test_part_i_is_reference_even_when_the_leaf_names_a_sector():
    assert themes_from_label("I.E.", "Généalogie et histoire de familles") == ["reference"]


def test_code_from_a_printed_path_keeps_the_number_tokens():
    path = [
        "III. Histoire par époques",
        "D. Époque contemporaine — Hedendaagse tijd",
        "2. La Belgique contemporaine",
        "a. Histoire politique",
    ]
    assert code_from_path(path) == "III.D.2.a."


def test_numbers_agree_only_when_the_leaf_matches():
    scheme = {
        "I.E.": SchemeEntry(
            "I.E.",
            "I.",
            "Généalogie et histoire de familles",
            "Genealogie",
            "",
            "vsmart",
            "",
        )
    }
    assert agreement_score("E. Généalogie et histoire de familles — Genealogie", "I.E.", scheme) >= 70
    assert agreement_score("E. Chronologie, Paléographie et Diplomatique", "I.E.", scheme) < 70


def test_an_unlabelled_parent_is_scored_against_its_children():
    scheme = {
        "I.B.2.": SchemeEntry("I.B.2.", "I.B.", "", "", "", "vsmart", ""),
        "I.B.2.a.": SchemeEntry("I.B.2.a.", "I.B.2.", "Inventaires", "Inventarissen", "", "vsmart", ""),
        "I.B.2.b.": SchemeEntry("I.B.2.b.", "I.B.2.", "Guides", "Gidsen", "", "vsmart", ""),
        "I.B.2.c.": SchemeEntry("I.B.2.c.", "I.B.2.", "Catalogues", "Catalogi", "", "vsmart", ""),
    }
    heading = "2. Inventaires, guides et catalogues — Inventarissen, gidsen en catalogi"
    assert agreement_score(heading, "I.B.2.", scheme) >= 70


def test_english_labels_are_marked_as_drafts():
    scheme = load_scheme()
    drafts = [entry for entry in scheme.values() if entry.label_en]
    assert drafts
    assert all("draft" in entry.note for entry in drafts)
