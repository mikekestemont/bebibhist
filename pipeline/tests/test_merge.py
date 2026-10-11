from bhb.io_utils import record_from_dict
from bhb.merge import merge_records
from bhb.model import Host, Person, Record
from bhb.mods import to_mods

NS = {"m": "http://www.loc.gov/mods/v3"}


def test_chapter_copies_the_book_subtitle_and_editors():
    book = Record(
        id="bhb:vs-1198861",
        source="vsmart",
        bgb_year=2012,
        type="book",
        title="Ene andre tale",
        subtitle="Tendensen in de Middelnederlandse late ridderepiek",
        persons=[
            Person("Faems", "An", "editor"),
            Person("Hogenbirk", "Marjolein", "editor"),
        ],
        bhb_codes=["II.A.3."],
    )
    chapter = Record(
        id="bhb:vs-1198871",
        source="vsmart",
        bgb_year=2012,
        type="article",
        title="Een 'Assonantic Revival'?",
        persons=[Person("Kestemont", "Mike")],
        host=Host(id="bhb:vs-1198861", year="2012", pages="259-290"),
        bhb_codes=["III.B.1.d."],
    )
    merged, _labels = merge_records([], [], [book, chapter])
    found = next(record for record in merged if record.id == "bhb:vs-1198871")
    assert found.type == "chapter"
    assert found.host is not None
    assert found.host.title == "Ene andre tale"
    assert found.host.subtitle == book.subtitle
    assert [(person.family, person.role) for person in found.host.editors] == [
        ("Faems", "editor"),
        ("Hogenbirk", "editor"),
    ]
    restored = record_from_dict(found.to_dict())
    assert restored.host is not None
    assert restored.host.editors[0].given == "An"

    root = to_mods(found)
    host = root.find("m:relatedItem[@type='host']", NS)
    assert host is not None
    assert host.findtext("m:titleInfo/m:subTitle", namespaces=NS) == book.subtitle
    assert host.findall("m:name/m:role/m:roleTerm", NS)[0].text == "edt"
    assert [part.text for part in host.findall("m:name/m:namePart[@type='family']", NS)] == [
        "Faems",
        "Hogenbirk",
    ]
