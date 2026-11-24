"""A new build against the data on the site (bhb compare)."""

from bhb.compare import compare, newest_deployed


def _rows(n, **fields):
    return {f"bhb:2000-{i}": {"id": f"bhb:2000-{i}", "source": "print-straive", "bgb_year": 2000, "title": f"Titel {i}", **fields} for i in range(n)}


def test_the_same_data_raises_nothing():
    assert compare(_rows(300, kbr="1"), _rows(300, kbr="1"))[1] == []


def test_a_year_that_shrank_and_a_field_that_lost_values_stop_the_release():
    old, new = _rows(300, kbr="1"), _rows(300, kbr="1")
    for i in range(60):
        new[f"bhb:2000-{i}"]["kbr"] = None
    assert compare(old, new)[1] == ["kbr: lost on 60 of 300 entries"]
    assert any("went from 300 to 200" in problem for problem in compare(old, _rows(200, kbr="1"))[1])


def test_a_link_that_turned_round_is_not_lost():
    old, new = _rows(200), _rows(200)
    for i in range(0, 200, 2):
        old[f"bhb:2000-{i}"]["duplicate_of"] = f"bhb:2000-{i + 1}"
        new[f"bhb:2000-{i + 1}"]["duplicate_of"] = f"bhb:2000-{i}"
    assert compare(old, new)[1] == []


def test_the_newest_deployed_data_is_compared_with(tmp_path):
    for day in ("2026-11-21", "2026-11-24"):
        (tmp_path / f"records.deployed-{day}.jsonl").write_text("")
    assert newest_deployed(tmp_path).name == "records.deployed-2026-11-24.jsonl"
