import dataclasses

from bhb.io_utils import record_from_dict
from bhb.model import Record


def test_every_field_of_a_record_survives_a_round_trip():
    # A field the reader leaves out is lost by every step that reads the build and writes it back: the map of
    # subjects lost its regions when `bhb similar` ran after `bhb topicmap apply` (11 Nov 2026).
    record = Record(id="bhb:2000-1", source="print-straive", bgb_year=2000, title="Les béguinages")
    record.topic_xy = [0.25, 0.75]
    record.topic = "r1.15"
    record.similar, record.similar_scores = ["bhb:2000-2"], [0.71]
    restored = record_from_dict(record.to_dict())
    assert restored.topic_xy == [0.25, 0.75]
    assert restored.topic == "r1.15"
    assert restored.similar == ["bhb:2000-2"]
    data = record.to_dict()
    for field in dataclasses.fields(Record):
        if field.name in data:
            assert restored.to_dict().get(field.name) == data[field.name], field.name
