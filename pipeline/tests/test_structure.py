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


def test_label_repair_keeps_letters_and_is_not_pushed_on_by_a_misreading():
    # BGB 1983: entries inserted as 38970a, 38970b once shifted 409 later numbers by 8.
    assert repair_labels(["38970", "38970a", "38970b", "38971"]) == [
        ("38970", False), ("38970a", False), ("38970b", False), ("38971", False),
    ]
    # One misreading is repaired, and the numbers after it stay as printed.
    assert repair_labels(["3170", "3171", "9172", "3173", "3174"]) == [
        ("3170", False), ("3171", False), ("3172", True), ("3173", False), ("3174", False),
    ]
    # A misread suffixed label belongs to the number before it.
    assert repair_labels(["44158", "44159", "47159b", "47159c", "44160", "44161"]) == [
        ("44158", False), ("44159", False), ("44159b", True), ("44159c", True), ("44160", False), ("44161", False),
    ]


def test_letter_i_after_h_is_not_a_new_part():
    stack: list[tuple[int, str]] = []
    stack = push_heading(stack, "I. Bibliographies et sciences auxiliaires")
    stack = push_heading(stack, "H. Géographie")
    stack = push_heading(stack, "I. Sciences linguistiques")
    # Letter I continues the A–Z series, so it stays under the bibliography part.
    assert path_of(stack) == [
        "I. Bibliographies et sciences auxiliaires",
        "I. Sciences linguistiques",
    ]
    assert [level for level, _text in stack] == [1, 2]


def test_unnumbered_heading_is_a_child_of_the_last_numbered():
    stack: list[tuple[int, str]] = []
    stack = push_heading(stack, "A. Bibliographies")
    stack = push_heading(stack, "Les villes — De steden")
    assert [level for level, _text in stack] == [2, 3]


def test_unnumbered_themes_are_siblings():
    # 1955: L'Expansion coloniale sits next to Les mouvements ouvriers, not under it.
    stack: list[tuple[int, str]] = []
    for text in (
        "II. Histoire par époques — Geschiedenis in tijdvakken",
        "F. De 1789 à nos jours. — Van 1789 tot heden.",
        "4. Après 1830. — Sedert 1830.",
        "La dynastie, les événements militaires et diplomatiques.",
        "La politique intérieure. — Binnenlandse politiek.",
        "Les mouvements ouvriers. — De arbeidersbewegingen.",
        "L'Expansion coloniale. — De coloniale expansie.",
    ):
        stack = push_heading(stack, text)
    assert [level for level, _text in stack] == [1, 2, 3, 4]
    assert stack[-1][1].startswith("L'Expansion coloniale")
    assert stack[-2][1].startswith("4. Après 1830")
    assert all("mouvements ouvriers" not in text for _level, text in stack)


def test_brabant_is_a_letter_not_a_part():
    for heading in (
        "I. Brabant, Limbourg, Outre-Meuse, Malines — Brabant, Limburg, Overmaas, Mechelen",
        "I. Brabant, Lim bourg, Outre-Meuse, Malines Brabant, Limburg, Over-Maas, Mechelen",
        "I. Brabant, Limbourg, Outre-M euse, Malines—Brabant, Limburg, Over-maas en Mechelen",
    ):
        stack: list[tuple[int, str]] = []
        stack = push_heading(stack, "III. Histoire par époques — Geschiedenis in tijdvakken")
        stack = push_heading(stack, "C. Les différentes principautés — De vorstendommen")
        stack = push_heading(stack, heading)
        assert [level for level, _text in stack] == [1, 2]
        assert stack[-1][1] == heading
        assert "aux" not in periods_from_path(path_of(stack))


def test_part_one_is_auxiliary_and_part_three_uses_keywords():
    # The auxiliary-sciences part is a subject area, not a period.
    assert periods_from_path(["I. Bibliographies et sciences auxiliaires"]) == []
    assert periods_from_path(["II. Ouvrages généraux"]) == ["general"]
    assert periods_from_path(["I. Généralités — Algemeenheden"]) == ["general"]
    assert periods_from_path(
        ["III. Histoire par époques", "D. Époque contemporaine", "1789"]
    ) == ["contemporary"]
    assert periods_from_path(
        ["II. Histoire par époques — Geschiedenis in tijdvakken", "F. De 1789 à nos jours."]
    ) == ["contemporary"]
    assert periods_from_path(
        ["III. Histoire par époques", "Histoire sociale et économique, 1789–1970"]
    ) == ["contemporary"]
    # A range that ends in 1789 is the early-modern period's end, not the contemporary period.
    assert periods_from_path(["III. Histoire par époques", "Les Temps modernes, 1500–1789"]) == ["early-modern"]
    assert "early-modern" in periods_from_path(
        ["III. Histoire par époques", "Les Pays-Bas espagnols et la principauté de Liège"]
    )


def test_vsmart_codes_map_onto_the_same_periods():
    assert periods_from_codes(["I.A.", "III.D.2.b.5."]) == ["contemporary"]
    assert periods_from_codes(["III.B.1.a.", "III.B.3."]) == ["medieval", "burgundian"]
    assert periods_from_codes(["III.C.1."]) == ["early-modern"]
    assert assign_period(["III. Histoire"], ["III.A.1."]) == ["ancient"]
