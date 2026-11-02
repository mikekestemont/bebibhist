"""Former ids: an entry renumbered by a repair keeps the id it had, matched on its place in the delivered file."""

import json

from bhb.ids import carry_former_ids, previous_ids
from bhb.model import Provenance, Record


def test_a_renumbered_entry_and_its_contributions_keep_their_former_ids(tmp_path):
    earlier = tmp_path / "records.jsonl"
    rows = [
        {"id": "bhb:1983-38992", "provenance": {"file": "/raw/BGB_1983.xml", "xml_id": "ref194"}},
        {"id": "bhb:1983-38992-c1", "provenance": {"file": "/raw/BGB_1983.xml", "xml_id": "ref194"}},
        {"id": "bhb:1983-38960", "provenance": {"file": "/raw/BGB_1983.xml", "xml_id": "ref150"}},
    ]
    earlier.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    volume = Record(id="bhb:1983-38984", source="print-straive", bgb_year=1983,
                    provenance=Provenance(file="/other/raw/BGB_1983.xml", xml_id="ref194"))
    chapter = Record(id="bhb:1983-38984-c1", source="print-straive", bgb_year=1983,
                     provenance=Provenance(file="/other/raw/BGB_1983.xml", xml_id="ref194"))
    same = Record(id="bhb:1983-38960", source="print-straive", bgb_year=1983,
                  provenance=Provenance(file="/raw/BGB_1983.xml", xml_id="ref150"))
    assert carry_former_ids([volume, chapter, same], previous_ids(earlier)) == {
        "bhb:1983-38992": "bhb:1983-38984", "bhb:1983-38992-c1": "bhb:1983-38984-c1",
    }
    assert volume.former_ids == ["bhb:1983-38992"]
    assert chapter.former_ids == ["bhb:1983-38992-c1"]
    assert same.former_ids == []


def test_stored_ids_move_all_at_once(tmp_path):
    from bhb.ids import migrate_ids

    folder = tmp_path / "build" / "identifiers"
    folder.mkdir(parents=True)
    (folder / "kbr.csv").write_text("id,chapters\nbhb:1983-38992,bhb:1983-38992-c1;bhb:1983-38993\nbhb:1983-38984,\n", encoding="utf-8")
    mapping = {"bhb:1983-38992": "bhb:1983-38984", "bhb:1983-38992-c1": "bhb:1983-38984-c1", "bhb:1983-38984": "bhb:1983-38975"}
    assert migrate_ids(tmp_path, mapping) == {"build/identifiers/kbr.csv": 3}
    assert (folder / "kbr.csv").read_text(encoding="utf-8") == (
        "id,chapters\nbhb:1983-38984,bhb:1983-38984-c1;bhb:1983-38993\nbhb:1983-38975,\n"
    )
