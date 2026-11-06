from bhb.corrections import apply_corrections
from bhb.model import Person, Record
from bhb.name_ocr import misread, proposals


def _record(record_id: str, family: str, given: str, source: str = "print-straive") -> Record:
    printed = f"{family} ({given}). Een titel. Gent, 1960, 10 p."
    return Record(id=record_id, source=source, bgb_year=1960, title="Een titel", printed=printed, persons=[Person(family, given)])


def test_letters_of_the_same_shape_and_a_space_inside_a_word_are_misreadings():
    assert misread("huybrecbts", "huybrechts")
    assert misread("beterarns", "beterams")
    assert misread("lindem ans", "lindemans")
    assert not misread("du chesne", "duchesne")
    assert not misread("vander made", "van der made")
    assert not misread("goppens", "goosens")
    assert not misread("kersemans", "kerremans")


def test_a_name_printed_once_is_corrected_to_the_frequent_name_kbr_knows():
    records = [_record(f"bhb:1960-{n}", "Zumkir", "André") for n in range(3)]
    records += [
        _record("bhb:1960-9", "Zumklr", "A."),
        # Known to KBR: a real name, left alone.
        _record("bhb:1960-10", "Zumkin", "A."),
        # Another given name: another person.
        _record("bhb:1960-11", "Zurnkir", "Pierre"),
        # Typed in the catalogue, not misread.
        _record("bhb:vs-1", "Zunkir", "A.", source="vsmart"),
    ]
    rows = proposals(records, {"zumkir", "zumkin"}, "2026-11-06")
    assert [(row["id"], row["wrong"], row["right"], row["kind"]) for row in rows] == [("bhb:1960-9", "Zumklr", "Zumkir", "name")]

    target = records[3]
    assert apply_corrections(records, rows) == 1
    assert target.persons[0].family == "Zumkir"
    assert target.printed.startswith("Zumklr (A.)")
    assert "corrected-name-machine" in target.provenance.flags


def test_corrections_apply_again_after_the_citation_pass_rewrote_the_names():
    record = _record("bhb:1960-9", "Zumklr", "A.")
    row = {"id": "bhb:1960-9", "wrong": "Zumklr", "right": "Zumkir", "kind": "name", "checked_by": "machine: test"}
    assert apply_corrections([record], [row]) == 1
    # The model's reading, made from the uncorrected text, replaces the people.
    record.persons = [Person("Zumklr", "A.")]
    assert apply_corrections([record], [row], again=True) == 1
    assert record.persons[0].family == "Zumkir"
    assert record.provenance.flags.count("corrected-name-machine") == 1
