from pathlib import Path

from bhb.ingest.jats import load_jats
from bhb.ingest.pdf_volume import PdfLine, segment
from bhb.ingest.vsmart import load_vsmart, render_printed_fields
from bhb.model import Host, Person
from bhb.paths import repo_root

STRAIVE = """<?xml version="1.0"?>
<article>
 <back>
  <ref-list><title>I. Bibliographies et sciences auxiliaires (1)</title>
   <ref-list><title>A. Méthodologie — Methodologie</title>
    <ref id="ref1"><label>100</label>
     <mixed-citation publication-type="jounal">
      <person-group person-group-type="author">
       <string-name><surname>Van Eenoo</surname> (<given-names>R.</given-names>)</string-name>
      </person-group>.
      <article-title>Bibliographie de l'histoire</article-title>.
      <source>Rev. belge</source>, <volume>LIII</volume>, <year>1975</year>, pp.
      <fpage>10</fpage>–<lpage>12</lpage>.
      <trans-title>[Cfr. n° 100]</trans-title>
     </mixed-citation>
    </ref>
    <ref id="ref2"><label>80048005</label>
     <mixed-citation publication-type="book">
      <person-group person-group-type="author">
       <string-name><surname>Colin</surname> (<given-names>G.</given-names>)</string-name>
      </person-group> (éd.).
      <source>Notes bibliographiques</source>.
      <publisher-loc>Bruxelles</publisher-loc>, <publisher-name>Culture</publisher-name>,
      <year>1975</year>, 28 p.
     </mixed-citation>
    </ref>
    <ref id="ref3"><label>102</label>
     <mixed-citation publication-type="unknown">Dhondt (J.). Une note. Revue du Nord, XLVI, 1964, pp. 1-2. — Annotation.</mixed-citation>
    </ref>
   </ref-list>
  </ref-list>
 </back>
</article>
"""

VSMART = """<?xml version="1.0"?>
<export>
 <BibDocumentsUniMarcB.Record Value="2^1214070">
  <_686vCoderingjaarinBHB-BGB Cnt="1">2013, tome 91</_686vCoderingjaarinBHB-BGB>
  <_686aHoofdgeleding Cnt="1">III.D.2.b.5. Geschiedenis in tijdvakken / Hedendaagse tijd / De financiën</_686aHoofdgeleding>
  <_686aHoofdgeleding Cnt="2">III.D.2.b.5. Histoire par époques / Epoque contemporaine / Les finances</_686aHoofdgeleding>
  <_700aEntryElement Cnt="1">Van De Perre</_700aEntryElement>
  <_700bPartofNameOtherthanEntryElement Cnt="1">Dirk</_700bPartofNameOtherthanEntryElement>
  <_7004Functiecode-Verwoording Cnt="1">Auteur</_7004Functiecode-Verwoording>
  <_701aEntryElement Cnt="1">Peeters</_701aEntryElement>
  <_701bPartofNameOtherthanEntryElement Cnt="1">Ann</_701bPartofNameOtherthanEntryElement>
  <_7014Functiecode-Verwoording Cnt="1">Onder leiding van</_7014Functiecode-Verwoording>
  <_200aHoofdtitel Cnt="1">De aankomst van de relieken</_200aHoofdtitel>
  <_200eAnderetitelinformatie Cnt="1">Een studie</_200eAnderetitelinformatie>
  <_200bAlgemenemateriaalaanduiding Cnt="1">Artikel/Article</_200bAlgemenemateriaalaanduiding>
  <_210dDatumvanuitgavedistributieetc. Cnt="1">2013</_210dDatumvanuitgavedistributieetc.>
  <_210a Cnt="1">Erembodegem</_210a>
  <_4630 Cnt="1">Bib:2:16948</_4630>
  <_463vVolumenummer Cnt="1">2013, jg. LXV, nr. 4, p. 286-289</_463vVolumenummer>
  <Trefwoorden Cnt="1">ignore me</Trefwoorden>
 </BibDocumentsUniMarcB.Record>
 <BibDocumentsUniMarcB.Record Value="2^16948">
  <_200aHoofdtitel Cnt="1">Handelingen</_200aHoofdtitel>
  <_200bAlgemenemateriaalaanduiding Cnt="1">Tijdschrift/Revue</_200bAlgemenemateriaalaanduiding>
  <_686vCoderingjaarinBHB-BGB Cnt="1">070</_686vCoderingjaarinBHB-BGB>
 </BibDocumentsUniMarcB.Record>
</export>
"""


def test_straive_fixture_repairs_labels_and_reads_tags(tmp_path: Path):
    path = tmp_path / "BGB_1975.xml"
    path.write_text(STRAIVE, encoding="utf-8")
    records = load_jats(path, "print-straive")
    assert [record.print_number for record in records] == ["100", "101", "102"]
    assert records[0].id == "bhb:1975-100"
    assert "label-repaired" in records[1].provenance.flags
    assert records[1].print_number == "101"
    assert records[0].persons[0].family == "Van Eenoo"
    assert records[0].title == "Bibliographie de l'histoire"
    assert records[0].host is not None and records[0].host.title == "Rev. belge"
    assert records[0].host.volume == "LIII"
    assert records[0].year == 1975
    assert records[0].host.pages == "10–12"
    assert records[0].title_translated is None
    assert "bhb:1975-100" in records[0].cross_refs
    assert records[0].section_path[0].startswith("I. Bibliographies")
    assert "(1)" not in records[0].section_path[0]
    assert records[0].section_path[1].startswith("A. Méthodologie")
    assert records[1].type == "book"
    assert records[1].persons[0].role == "editor"
    assert records[1].publisher.place == "Bruxelles"
    assert records[2].type == "article"
    assert records[2].note.startswith("Annotation")
    assert "XVI" not in (records[0].printed or "")
    assert "ᵉ" in _superscript_sample(tmp_path)


def _superscript_sample(tmp_path: Path) -> str:
    path = tmp_path / "BGB_1976.xml"
    path.write_text(
        """<?xml version="1.0"?><article><back><ref-list><title>I. Algemeen</title>
        <ref id="r"><label>1</label><mixed-citation publication-type="book">
        <source>Siècle</source> XVI<sup>e</sup>.</mixed-citation></ref></ref-list></back></article>""",
        encoding="utf-8",
    )
    return load_jats(path, "print-straive")[0].printed or ""


def test_pdf_segmentation_joins_entries_and_keeps_bis():
    lines = [
        PdfLine(1, "This introduction mentions 1952 and should be skipped entirely."),
        PdfLine(2, "I. BIBLIOGRAPHIES ET SCIENCES AUXILIAIRES"),
        PdfLine(2, "- BIBLIOGRAFIEËN EN HULPWETENSCHAPPEN"),
        PdfLine(2, "60343bis Nys (Liesbet). Aspirations to life. Journal, XX, 2008, 1, pp. 113-126."),
        PdfLine(3, "60344 Sauwen (Rik). The British Royal Collection."),
        PdfLine(3, "Gent, Openbaar Kunstbezit, 2008, 20 p."),
        PdfLine(3, "C. Codicologie - Handschriftkunde(1)"),
        PdfLine(3, "60345 Shawe-Taylor (Desmond). Van Bruegel tot Rubens. Brussel, Boekhuis, 2008, 223 p."),
        PdfLine(4, "61024 750e anniversaire de Gérouville, 1258-2008. Virton, Chronique, 2008, 40 p."),
        PdfLine(4, "63371 vanden Daelen (Veerle). Jews, cemeteries, and the city. In: A perspective."),
    ]
    blocks = segment(lines)
    headings = [block.text for block in blocks if block.kind == "heading"]
    entries = [block for block in blocks if block.kind == "entry"]
    assert headings[0].startswith("I. BIBLIOGRAPHIES")
    assert "BIBLIOGRAFIEËN" in headings[0]
    assert [block.number for block in entries] == ["60343bis", "60344", "60345", "61024", "63371"]
    assert entries[3].text.startswith("750e")
    assert entries[4].text.startswith("vanden Daelen")
    assert "Openbaar Kunstbezit" in entries[1].text
    assert entries[2].text.startswith("Shawe-Taylor")
    assert any(block.level == 2 for block in blocks if block.kind == "heading" and block.text.startswith("C."))


def test_vsmart_pairs_repeatable_fields_and_codes(tmp_path: Path):
    folder = tmp_path / "exports"
    folder.mkdir()
    (folder / "f1446.xml").write_text(VSMART, encoding="utf-8")
    records, labels = load_vsmart(folder)
    by_id = {record.id: record for record in records}
    article = by_id["bhb:vs-1214070"]
    assert article.bgb_year == 2013
    assert article.bhb_codes == ["III.D.2.b.5."]
    assert article.persons[0].family == "Van De Perre"
    assert article.persons[1].role == "editor"
    assert article.host.id == "bhb:vs-16948"
    assert article.host.volume == "LXV"
    assert article.host.issue == "4"
    assert article.host.pages == "286-289"
    assert article.year == 2013
    assert "Een studie" in (article.subtitle or "")
    assert labels["III.D.2.b.5."]["label_nl"].startswith("Geschiedenis")
    assert "finances" in labels["III.D.2.b.5."]["label_fr"]
    host = by_id["bhb:vs-16948"]
    assert host.type == "journal-issue"
    assert host.bgb_year == 2013  # file year; "070" is not a BGB year


def test_catalogue_line_does_not_double_the_final_stop():
    line = render_printed_fields(
        [Person("Bilteryst", "Damien")],
        "Philippe, comte de Flandre",
        "Frère de Léopold II",
        None,
        2014,
        "328 p.",
        "Bruxelles",
        "Racine",
    )
    assert line == "Bilteryst (Damien). Philippe, comte de Flandre: Frère de Léopold II. Bruxelles, Racine, 2014, 328 p."
    hosted = render_printed_fields(
        [Person("Murk-Jansen", "Saskia M.")],
        "Hadewijch",
        None,
        Host(title="Holy Women of the Low Countries", pages="663-688"),
        2010,
        None,
        None,
        None,
    )
    assert hosted.endswith("p. 663-688.")
    assert "In: Holy Women" in hosted


def test_editor_group_after_the_title_belongs_to_the_host(tmp_path: Path):
    path = tmp_path / "BGB_2000.xml"
    path.write_text(
        """<?xml version="1.0"?><article><back><ref-list><title>I. Algemeen</title>
        <ref id="ref1080"><label>29753</label><mixed-citation publication-type="other">
        <person-group person-group-type="author"><string-name><surname>Joldersma</surname> (<given-names>Hermina</given-names>)</string-name></person-group>.
        <chapter-title>Geestelijke liederen</chapter-title>. In:
        <person-group person-group-type="editor"><string-name><surname>Willaert</surname> (<given-names>Frank</given-names>)</string-name></person-group>.
        <source>Veelderhande liedekens</source>. pp. <fpage>58</fpage>–<lpage>73</lpage>. [Cfr. n° 29240]
        </mixed-citation></ref></ref-list></back></article>""",
        encoding="utf-8",
    )
    record = load_jats(path, "print-straive")[0]
    assert [(person.family, person.given) for person in record.persons] == [("Joldersma", "Hermina")]
    assert record.host is not None
    assert record.host.title == "Veelderhande liedekens"
    assert [(person.family, person.given, person.role) for person in record.host.editors] == [("Willaert", "Frank", "editor")]
    assert "bhb:2000-29240" in record.cross_refs


def test_real_1975_volume_round_trips_a_known_entry():
    path = repo_root() / "2023-12-29" / "BGB_1970-79" / "BGB_1975.xml"
    if not path.is_file():
        return
    records = load_jats(path, "print-straive")
    assert len(records) > 2000
    first = records[0]
    assert first.id == "bhb:1975-23701"
    assert first.persons[0].family == "Van Eenoo"
    assert "Bibliographie" in (first.title or "")
    assert first.printed and "Van Eenoo" in first.printed


def test_see_also_line_is_a_secondary_section_not_a_heading(tmp_path: Path):
    path = tmp_path / "BGB_1972.xml"
    path.write_text(
        """<?xml version="1.0"?><article><back>
        <ref-list><title>I. Bibliographies et sciences auxiliaires</title>
          <ref-list><title>A. Méthodologie</title>
            <ref id="a"><label>100</label><mixed-citation>Auteur. Titre. Bruxelles, 1972, 10 p.</mixed-citation></ref>
            <ref-list><title>(Voir aussi - Zie ook: 8447, 99999)</title></ref-list>
            <ref id="b"><label>101</label><mixed-citation>Autre. Titre. Gent, 1972, 12 p.</mixed-citation></ref>
          </ref-list>
          <ref-list><title>K. Folklore (Cfr n° 100)</title>
            <ref id="c"><label>8447</label><mixed-citation>Cible. Titre. Leuven, 1972, 8 p.</mixed-citation></ref>
          </ref-list>
        </ref-list></back></article>""",
        encoding="utf-8",
    )
    records = {record.print_number: record for record in load_jats(path, "print-straive")}
    assert all("Voir aussi" not in " ".join(record.section_path) for record in records.values())
    assert records["101"].section_path == [
        "I. Bibliographies et sciences auxiliaires",
        "A. Méthodologie",
    ]
    folklore = [
        "I. Bibliographies et sciences auxiliaires",
        "K. Folklore (Cfr n° 100)",
    ]
    assert records["8447"].section_path == folklore
    assert records["8447"].secondary_sections == [
        ["I. Bibliographies et sciences auxiliaires", "A. Méthodologie"]
    ]
    assert records["100"].secondary_sections == [folklore]
    assert "see-also-unresolved" in records["101"].provenance.flags
