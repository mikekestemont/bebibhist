import numpy as np

from bhb.model import Record
from bhb.topicmap import apply, centred, chain, distinctive_words, fix_names, layout_text, parse_name, regions, unit_square


def test_each_language_loses_its_mean_direction():
    rng = np.random.default_rng(1)
    dutch = rng.normal(size=(300, 8)) + np.array([3, 0, 0, 0, 0, 0, 0, 0])
    french = rng.normal(size=(300, 8)) + np.array([0, 3, 0, 0, 0, 0, 0, 0])
    out = centred(np.vstack([dutch, french]), ["nl"] * 300 + ["fr"] * 300)
    assert abs(out[:300, 0].mean()) < 0.1 and abs(out[300:, 1].mean()) < 0.1
    assert np.allclose(np.linalg.norm(out, axis=1), 1, atol=1e-5)


def test_positions_fit_the_unit_square_and_outliers_sit_on_the_edge():
    xy = np.vstack([np.random.default_rng(2).normal(size=(2000, 2)), [[500.0, 500.0]]])
    out = unit_square(xy)
    assert out.min() >= 0 and out.max() <= 1
    assert out[-1].tolist() == [1.0, 1.0]


def test_regions_nest_and_every_point_has_a_finest_region():
    xy = np.random.default_rng(3).random((3000, 2)).astype(np.float32)
    member, found = regions(xy, levels=(3, 9, 30))
    assert member.shape == (3000,) and member.max() < 30
    by_level = {level: [r for r in found if r.level == level] for level in (1, 2, 3)}
    assert len(by_level[1]) == 3 and all(r.parent is None for r in by_level[1])
    assert all(r.parent.startswith("r2.") for r in by_level[3])
    assert sum(r.n for r in by_level[1]) == sum(r.n for r in by_level[3]) == 3000
    assert all(len(path) == 3 for region_id, path in chain(found).items() if region_id.startswith("r3."))


def test_a_model_answer_gives_three_names_or_none():
    answer = '```json\n{"en": "Beguines and beguinages", "nl": "Begijnen en begijnhoven", "fr": "Béguines et béguinages"}\n```'
    assert parse_name(answer) == {"en": "Beguines and beguinages", "nl": "Begijnen en begijnhoven", "fr": "Béguines et béguinages"}
    assert parse_name('{"en": "Mills", "nl": "Molens"}') is None
    assert parse_name("I cannot name this region.") is None


def test_distinctive_words_leave_out_what_every_region_shares():
    texts = {
        "a": ["The beguinage of Bruges", "Beguines of Ghent", "The beguinage of Lier", "Beguinage and beguines"] * 2,
        "b": ["Mills of Bruges", "Water mills of Ghent", "Wind mills in Lier", "The mills and millers"] * 2,
    }
    words = distinctive_words(texts)
    assert words["a"][0] in {"beguinage", "beguines"} and words["b"][0] == "mills"
    assert "bruges" not in words["a"][:2]


def test_the_layout_text_is_the_english_translation_or_the_title():
    record = Record(id="bhb:1990-1", source="print-straive", bgb_year=1990, title="De begijnhoven van Vlaanderen")
    assert layout_text(record) == "De begijnhoven van Vlaanderen"
    record.translations = {"en": "The beguinages of Flanders."}
    assert layout_text(record) == "The beguinages of Flanders"


def test_apply_writes_positions_and_clears_entries_left_off_the_map():
    placed = Record(id="a", source="vsmart", bgb_year=2010, title="Een titel")
    other = Record(id="b", source="vsmart", bgb_year=2010, title="Andere", topic_xy=[0.1, 0.2], topic="r3.4")
    count = apply([placed, other], ["a"], np.array([[0.123456, 0.5]], dtype=np.float32), np.array([7]), 3)
    assert count == 1
    assert placed.topic_xy == [0.12346, 0.5] and placed.topic == "r3.7"
    assert other.topic_xy == [] and other.topic is None


def test_hand_corrections_replace_a_whole_name_in_one_language(tmp_path):
    fixes = tmp_path / "fixes.csv"
    fixes.write_text("language,wrong,right,note\nnl,Namur en omgeving,Namen en omgeving,\n", encoding="utf-8")
    names = {"r1.0": {"en": "Namur and its region", "nl": "Namur en omgeving", "fr": "Namur et sa région"}}
    assert fix_names(names, fixes) == 1
    assert names["r1.0"] == {"en": "Namur and its region", "nl": "Namen en omgeving", "fr": "Namur et sa région"}
