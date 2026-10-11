from lxml import etree

from bhb.ingest.jats import load_jats
from bhb.model import Category, Host, Person, Provenance, Publisher, Record
from bhb.mods import export_mods, to_mods

NS = {"m": "http://www.loc.gov/mods/v3"}


def test_book_mods_keeps_the_printed_line_and_the_imprint():
    record = Record(
        id="bhb:vs-1177675",
        source="vsmart",
        bgb_year=2011,
        printed="Hochschild (Adam). De geest van koning Leopold II en de plundering van de Congo. Amsterdam, Meulenhoff, 2011, 359 p..",
        type="book",
        title="De geest van koning Leopold II en de plundering van de Congo",
        persons=[Person("Hochschild", "Adam", "author")],
        publisher=Publisher(place="Amsterdam", name="Meulenhoff"),
        year=2011,
        extent="359 p.",
        bhb_codes=["III.D.2.a.4.i."],
        period=["contemporary"],
        provenance=Provenance(parser="vsmart@0.1", confidence=0.9),
    )
    root = to_mods(record)
    assert root.findtext("m:titleInfo/m:title", namespaces=NS) == record.title
    assert root.findtext("m:name/m:namePart[@type='family']", namespaces=NS) == "Hochschild"
    assert root.findtext("m:name/m:namePart[@type='given']", namespaces=NS) == "Adam"
    assert root.findtext("m:name/m:role/m:roleTerm", namespaces=NS) == "aut"
    assert root.findtext("m:originInfo/m:publisher", namespaces=NS) == "Meulenhoff"
    assert root.findtext("m:originInfo/m:place/m:placeTerm", namespaces=NS) == "Amsterdam"
    assert root.findtext("m:originInfo/m:dateIssued", namespaces=NS) == "2011"
    assert root.findtext("m:physicalDescription/m:extent", namespaces=NS) == "359 p."
    assert root.findtext("m:note[@type='printed citation']", namespaces=NS) == record.printed
    assert root.findtext("m:classification[@authority='bhb-period']", namespaces=NS) == "contemporary"
    assert root.findtext("m:classification[@authority='bhb']", namespaces=NS) == "III.D.2.a.4.i."
    assert root.findtext("m:recordInfo/m:recordContentSource", namespaces=NS) == "ARA V-Smart record 1177675"


def test_a_machine_category_is_marked_suggested():
    record = Record(
        id="bhb:1972-1",
        source="print-straive",
        bgb_year=1972,
        title="Un titre",
        categories=[
            Category(code="III.B.2.", source="classifier", confidence=0.74, machine=True, primary=True),
            Category(code="I.A.", source="see-also", confidence=1.0, machine=False, primary=False),
        ],
    )
    root = to_mods(record)
    primary = root.find("m:classification[@usage='primary']", namespaces=NS)
    assert primary is not None
    assert primary.text == "III.B.2."
    assert primary.get("displayLabel") == "machine-suggested"
    codes = root.findall("m:classification[@authority='bhb']", namespaces=NS)
    secondary = next(item for item in codes if item.get("usage") is None)
    assert secondary.text == "I.A."
    assert secondary.get("displayLabel") is None


def test_article_host_pages_split_and_uri_is_kept(tmp_path):
    record = Record(
        id="bhb:1975-23701",
        source="print-straive",
        bgb_year=1975,
        print_number="23701",
        printed="Van Eenoo (R.). Bibliographie. Rev. belge, LIII, 1975, pp. 10–12.",
        type="article",
        title="Bibliographie",
        persons=[Person("Van Eenoo", "R.", "editor")],
        host=Host(title="Rev. belge", volume="LIII", pages="10–12"),
        year=1975,
        links=["https://example.org/item"],
        provenance=Provenance(parser="jats-rules@0.1", confidence=0.95),
    )
    root = to_mods(record)
    assert root.findtext("m:name/m:role/m:roleTerm", namespaces=NS) == "edt"
    assert root.findtext("m:relatedItem[@type='host']/m:titleInfo/m:title", namespaces=NS) == "Rev. belge"
    assert root.findtext("m:relatedItem/m:part/m:extent/m:start", namespaces=NS) == "10"
    assert root.findtext("m:relatedItem/m:part/m:extent/m:end", namespaces=NS) == "12"
    assert root.findtext("m:location/m:url", namespaces=NS) == "https://example.org/item"
    assert "23701" in root.findtext("m:recordInfo/m:recordContentSource", namespaces=NS)

    path = tmp_path / "BGB_1976.xml"
    path.write_text(
        """<?xml version="1.0"?><article><back><ref-list><title>I. Algemeen</title>
        <ref id="r"><label>1</label><mixed-citation publication-type="book">
        <person-group person-group-type="author"><string-name>
        <surname>Peeters</surname> (<given-names>A.</given-names>)</string-name></person-group>.
        <source>Catalogus</source>. <publisher-loc>Gent</publisher-loc>, <publisher-name>Snoeck</publisher-name>,
        <year>1976</year>. <uri type="http://www.example.org/cat">www.example.org/cat</uri>
        </mixed-citation></ref></ref-list></back></article>""",
        encoding="utf-8",
    )
    loaded = load_jats(path, "print-straive")[0]
    assert loaded.links == ["http://www.example.org/cat"]
    assert "www.example.org/cat" in (loaded.printed or "")

    jsonl = tmp_path / "records.jsonl"
    jsonl.write_text(
        __import__("json").dumps(record.to_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    counts = export_mods(jsonl, tmp_path / "mods")
    assert counts == {"1975": 1}
    tree = etree.parse(str(tmp_path / "mods" / "bhb-1975.xml"))
    assert tree.getroot().tag == f"{{{NS['m']}}}modsCollection"
    assert tree.findtext(".//m:identifier[@type='bhb']", namespaces=NS) == "bhb:1975-23701"
