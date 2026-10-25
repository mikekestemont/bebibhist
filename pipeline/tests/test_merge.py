from bhb.io_utils import record_from_dict
from bhb.merge import heading_report_lines, heading_warnings, merge_records
from bhb.model import Host, Person, Publisher, Record
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


def test_chapter_borrows_the_collected_volume_year_and_keeps_the_printed_line():
    book = Record(
        id="bhb:1990-53024",
        source="print-straive",
        bgb_year=1990,
        type="book",
        title="Lokeren vroeger. Een huldeboek voor Vedastus Verstegen",
        year=1990,
        printed="Van Campenhout (Nico), ed. Lokeren vroeger. Een huldeboek. Brugge, Marc Van de Wiele, 1990, 152 p.",
    )
    printed = (
        "Van Campenhout (Nico). Anderhalve eeuw historisch onderzoek over Lokeren en omgeving. "
        "In : Lokeren vroeger, pp. 90–92. [Cfr. n° 53024]."
    )
    chapter = Record(
        id="bhb:1990-53047",
        source="print-straive",
        bgb_year=1990,
        type="chapter",
        title="Anderhalve eeuw historisch onderzoek over Lokeren en omgeving",
        host=Host(pages="90–92"),
        cross_refs=["bhb:1990-53024"],
        printed=printed,
    )
    see_also = Record(
        id="bhb:1990-53048",
        source="print-straive",
        bgb_year=1990,
        type="article",
        title="Zin en mogelijkheid van geschiedschrijving over de Nederlanden",
        year=1990,
    )
    other = Record(
        id="bhb:1990-53031",
        source="print-straive",
        bgb_year=1990,
        type="chapter",
        host=Host(pages="163–188"),
        cross_refs=["bhb:1990-53048"],
        printed=(
            "Van Peteghem (P.). De verzameling van de ordonnanties. "
            "In : Lambrecht (D.), ed. Lopend rechtshistorisch …, pp. 163–188. [Cfr. n° 53048]."
        ),
    )
    merged, _labels = merge_records([book, chapter, see_also, other], [], [])
    found = next(record for record in merged if record.id == chapter.id)
    assert found.year == 1990
    assert found.host is not None and found.host.year == "1990"
    assert found.printed == printed
    assert "year-from-host" in found.provenance.flags
    skipped = next(record for record in merged if record.id == other.id)
    assert skipped.year is None
    assert "year-from-host" not in skipped.provenance.flags


def test_chapter_takes_the_imprint_of_the_volume_its_cross_reference_names():
    book = Record(
        id="bhb:2000-29240",
        source="print-straive",
        bgb_year=2000,
        type="book",
        title="Veelderhande liedekens. Studies over het Nederlandse lied tot 1600",
        persons=[Person("Willaert", "Frank")],
        publisher=Publisher("Leuven", "Peeters"),
        year=1997,
    )
    printed = (
        "Joldersma (Hermina). ‘Geestelijke’ en ‘wereldlijke’ liederen. "
        "In: Willaert (Frank). Veelderhande liedekens. pp. 58–73. [Cfr. n° 29240]"
    )
    chapter = Record(
        id="bhb:2000-29753",
        source="print-straive",
        bgb_year=2000,
        type="chapter",
        host=Host(title="Veelderhande liedekens", pages="58–73", editors=[Person("Willaert", "Frank", "editor")]),
        cross_refs=["bhb:2000-29240"],
        printed=printed,
    )
    stray = Record(
        id="bhb:2000-29754",
        source="print-straive",
        bgb_year=2000,
        type="chapter",
        host=Host(title="Andere bundel", pages="1–9"),
        cross_refs=["bhb:2000-29240"],
        printed="Iemand (A.). Iets. In: Andere bundel over iets anders. pp. 1–9. [Cfr. n° 29240]",
    )
    merged, _labels = merge_records([book, chapter, stray], [], [])
    found = next(record for record in merged if record.id == chapter.id)
    assert found.host is not None
    assert found.host.id == book.id
    assert found.host.title == "Veelderhande liedekens"
    assert found.host.publisher == Publisher("Leuven", "Peeters")
    assert found.publisher is None
    assert found.printed == printed
    assert "host-from-cross-ref" in found.provenance.flags
    assert record_from_dict(found.to_dict()).host.publisher == Publisher("Leuven", "Peeters")
    host = to_mods(found).find("m:relatedItem[@type='host']", NS)
    assert host.findtext("m:originInfo/m:publisher", namespaces=NS) == "Peeters"
    assert host.findtext("m:originInfo/m:place/m:placeTerm", namespaces=NS) == "Leuven"
    other = next(record for record in merged if record.id == stray.id)
    assert other.host is not None and other.host.id is None
    assert "host-from-cross-ref" not in other.provenance.flags


def test_heading_report_warns_when_a_top_heading_is_not_a_part():
    records = [
        Record(
            id="bhb:1972-1",
            source="print-straive",
            bgb_year=1972,
            role="entry",
            section_path=["I. Brabant, Limbourg, Outre-Meuse"],
            period=[],
        ),
        Record(
            id="bhb:1972-2",
            source="print-straive",
            bgb_year=1972,
            role="entry",
            section_path=["III. Histoire par époques — Geschiedenis in tijdvakken", "B. Moyen âge"],
            period=["medieval"],
        ),
    ]
    warnings = heading_warnings(records)
    assert any("Brabant" in warning for warning in warnings)
    assert not any("Histoire par époques" in warning for warning in warnings)
    text = "\n".join(heading_report_lines(records))
    assert "| 1972 |" in text
    assert "50.0%" in text
