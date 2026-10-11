import gzip
import json
from collections import Counter

from bhb.release import release_command, render_notes, write_release


def test_release_packs_the_derived_records_and_credits_the_licence(tmp_path):
    records = tmp_path / "records.jsonl"
    rows = [{"id": "a", "source": "print-straive"}, {"id": "b", "source": "vsmart"}, {"id": "c", "source": "vsmart"}]
    records.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    notes = write_release(records, tmp_path / "release", built_on="2026-10-11", commit="abc1234")
    text = notes.read_text(encoding="utf-8")
    assert "derived dataset, not the raw sources" in text
    assert "2026-10-11" in text
    assert "abc1234" in text
    assert "CC BY-NC 4.0" in text
    assert "https://creativecommons.org/licenses/by-nc/4.0/" in text
    assert "CC BY 4.0" not in text.replace("CC BY-NC 4.0", "")
    with gzip.open(tmp_path / "release" / "records.jsonl.gz", "rt", encoding="utf-8") as handle:
        packed = [json.loads(line) for line in handle if line.strip()]
    assert packed == rows


def test_notes_list_every_source():
    text = render_notes(Counter({"vsmart": 2, "print-pdf": 1}), "2026-10-11", "abc")
    assert "| print-pdf | 1 |" in text
    assert "| vsmart | 2 |" in text
    assert "| **Total** | 3 |" in text


def test_release_command_uses_the_data_tag():
    command = release_command("2026-10-11")
    assert command.startswith("gh release create data-2026-10-11 ")
    assert "build/release/records.jsonl.gz" in command
    assert "build/release/NOTES.md" in command
