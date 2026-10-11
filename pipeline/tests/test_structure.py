from bhb.facets import assign_period, periods_from_codes, periods_from_path
from bhb.labels import repair_labels
from bhb.sections import path_of, push_heading


def test_label_repair_replaces_a_number_outside_its_neighbours():
    repaired = repair_labels(["100", "80048005", "102"])
    assert repaired == [("100", False), ("101", True), ("102", False)]


def test_label_repair_keeps_bis_and_real_gaps():
    assert repair_labels(["8544", "8544bis", "8545"]) == [
        ("8544", False),
        ("8544bis", False),
        ("8545", False),
    ]
    assert repair_labels(["50", "52"]) == [("50", False), ("52", False)]


def test_letter_i_after_h_is_not_a_new_part():
    stack: list[tuple[int, str]] = []
    stack = push_heading(stack, "I. Bibliographies")
    stack = push_heading(stack, "H. Géographie")
    stack = push_heading(stack, "I. Sciences linguistiques")
    # Letter I continues the A–Z series, so it stays under part I instead of opening a new part.
    assert path_of(stack) == ["I. Bibliographies", "I. Sciences linguistiques"]
    assert [level for level, _text in stack] == [1, 2]


def test_unnumbered_heading_is_a_child():
    stack: list[tuple[int, str]] = []
    stack = push_heading(stack, "A. Bibliographies")
    stack = push_heading(stack, "Les villes — De steden")
    assert [level for level, _text in stack] == [2, 3]


def test_part_one_is_auxiliary_and_part_three_uses_keywords():
    assert periods_from_path(["I. Bibliographies et sciences auxiliaires"]) == ["aux"]
    assert periods_from_path(["II. Ouvrages généraux"]) == ["general"]
    assert periods_from_path(
        ["III. Histoire par époques", "D. Époque contemporaine", "1789"]
    ) == ["contemporary"]
    assert "early-modern" in periods_from_path(
        ["III. Histoire par époques", "Les Pays-Bas espagnols et la principauté de Liège"]
    )


def test_vsmart_codes_map_onto_the_same_periods():
    assert periods_from_codes(["I.A.", "III.D.2.b.5."]) == ["aux", "contemporary"]
    assert periods_from_codes(["III.B.1.a.", "III.B.3."]) == ["medieval", "burgundian"]
    assert periods_from_codes(["III.C.1."]) == ["early-modern"]
    assert assign_period(["III. Histoire"], ["III.A.1."]) == ["ancient"]
