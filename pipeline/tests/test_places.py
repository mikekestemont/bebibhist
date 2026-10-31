"""Places from the printed place indexes, resolved against the gazetteer."""

from pathlib import Path

from bhb.places import parse_index, resolve, year_of_index


def _index(tmp_path: Path, paragraphs: list[str]) -> Path:
    path = tmp_path / "Beknopte_Index_van_Plaatsnamen.xml"
    body = "".join(f"<p>{text}</p>" for text in paragraphs)
    path.write_text(f'<?xml version="1.0"?><article><body>{body}</body></article>', encoding="utf-8")
    return path


def test_an_index_line_gives_its_numbers_and_a_sub_entry_belongs_to_the_place_above(tmp_path: Path):
    lines = parse_index(_index(tmp_path, [
        "Aachen: 20649, 21012 (Voir aussi - Zie ook: Aix-la-Chapelle)",
        "Aalst: 20592, 21161;",
        "Land: 21107, 21108",
        "Aalter: 22801",
    ]))
    assert [(line.place, line.detail, line.numbers) for line in lines] == [
        ("Aachen", None, ["20649", "21012"]),
        ("Aalst", None, ["20592", "21161"]),
        ("Aalst", "Land", ["21107", "21108"]),
        ("Aalter", None, ["22801"]),
    ]
    assert lines[0].see_also == ["Aix-la-Chapelle"]


def test_the_index_belongs_to_the_volume_whose_numbers_it_matches(tmp_path: Path):
    lines = parse_index(_index(tmp_path, ["Gent: 100, 101, 102", "Brugge: 103"]))
    assert year_of_index(lines, {1994: {"100", "101", "102", "103"}, 1995: {"100"}}) == 1994
    assert year_of_index(lines, {1995: {"100"}}) is None


def test_a_name_resolves_to_a_municipality_before_a_province_or_a_section():
    rows = {
        "11002": {"level": "municipality"},
        "10000": {"level": "area"},
        "44021": {"level": "municipality"},
        "13040A": {"level": "section"},
        "23027": {"level": "municipality"},
    }
    labels = {"antwerpen": ["10000", "11002"], "gent": ["44021"], "gand": ["44021"], "halle": ["13040A", "23027"]}
    assert resolve("Antwerpen", rows, labels) == "11002"
    assert resolve("Gand", rows, labels) == resolve("Gent", rows, labels) == "44021"
    assert resolve("Halle", rows, labels) == "23027"
    assert resolve("Wallonie", rows, labels) is None


def test_two_codes_for_one_place_before_and_after_a_merger_resolve_to_the_first():
    rows = {"82003": {"level": "municipality", "lon": "5.72", "lat": "50.00"}, "82039": {"level": "municipality", "lon": "5.73", "lat": "50.01"}}
    assert resolve("Bastogne", rows, {"bastogne": ["82039", "82003"]}) == "82003"


def test_limburg_is_the_province_and_limbourg_the_town():
    rows = {"63046": {"level": "municipality"}, "70000": {"level": "area"}}
    labels = {"limburg": ["63046", "70000"], "limbourg": ["63046", "70000"]}
    assert resolve("Limburg", rows, labels) == "70000"
    assert resolve("Limbourg", rows, labels) == "63046"


def test_a_place_abroad_stays_as_printed():
    rows = {"13019": {"level": "municipality"}}
    labels = {"lille": ["13019"]}
    assert resolve("Lille", rows, labels) is None
    assert resolve("Lille (France)", rows, labels) is None
    assert resolve("Lille (België)", rows, labels) == "13019"


def _matcher():
    from bhb.places import TitleMatcher

    rows = {
        "44021": {"level": "municipality"}, "62063": {"level": "municipality"}, "92094": {"level": "municipality"},
        "53053": {"level": "municipality"}, "40000": {"level": "area"}, "21004X": {"level": "section"},
    }
    labels = {
        "gent": ["44021"], "gand": ["44021"], "liege": ["62063"], "luik": ["62063"], "namen": ["92094"],
        "bergen": ["53053"], "oost vlaanderen": ["40000"], "saint martin": ["21004X"],
    }
    return TitleMatcher.from_gazetteer(rows, labels)


def test_title_places_skip_conference_venues_and_keep_the_subject():
    matcher = _matcher()
    assert matcher.find("Weduwen en wezen in het laat-middeleeuwse Gent") == [("gent", "44021")]
    assert matcher.find("Gender & klasse. Internationaal colloquium, Gent, 27–30 april 1999") == []
    assert matcher.find("Actes du colloque tenu à Gand") == []
    assert matcher.find("Congrès de Liège, 20–23 VIII. 1992. Actes") == []
    assert matcher.find("11ᵉ Colloque international. Gand. — Actes") == []
    assert matcher.find("Actes du colloque. Gand au XIXe siècle") == [("gand", "44021")]
    # The editors index a place of birth, an exhibition, an archive: so does the matcher.
    assert matcher.find("Antoon Vleminck (Antwerpen 1573 - Gent 1640)") == [("gent", "44021")]


def test_title_places_need_a_capital_and_skip_areas_saints_and_homonyms():
    matcher = _matcher()
    assert matcher.find("le gent") == []
    assert matcher.find("Oost-Vlaanderen") == []
    assert matcher.find("L'église Saint-Martin") == []
    assert matcher.find("Völker, Reiche und Namen im frühen Mittelalter") == []
    assert matcher.find("De vesting Bergen op Zoom") == []
    assert matcher.find("Het beleg van Bergen en Luik") == [("bergen", "53053"), ("luik", "62063")]
