"""The editor's Word manuscripts: a small .docx in the layout of BGBBHB2020def.docx."""

import zipfile

from bhb.ingest.manuscript import bold_names, load_manuscript, manuscript_paths, year_of

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def run(text, bold=False, italic=False):
    marks = ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "")
    props = f"<w:rPr>{marks}</w:rPr>" if marks else ""
    pieces = text.split("\t")
    body = "<w:tab/>".join(f'<w:t xml:space="preserve">{piece}</w:t>' for piece in pieces)
    return f"<w:r>{props}{body}</w:r>"


def paragraph(*runs):
    return f"<w:p>{''.join(runs)}</w:p>"


def entry(authors, title, rest):
    return paragraph(run(authors, bold=True), run(title, italic=True), run(rest))


PARAGRAPHS = [
    paragraph(run("Kennisgeving", bold=True)),
    paragraph(run("Sedert 1992-1993 verschenen er in de Bibliografie indices.")),
    paragraph(run("I. Bibliographies et sciences auxiliaires – Bibliografieën en hulpwetenschappen", bold=True)),
    paragraph(run("A. Bibliographies courantes", bold=True)),
    paragraph(run("Lopende bibliografieën", bold=True)),
    entry("Kempeneers (Paul). ", "Eigendommen van baron de Warlusel in Dormaal. ",
          "Oost-Brabant. Heemkundig Tijdschrift voor het Hageland en Omgeving, LVII, 2020, 4, pp. 67-68."),
    entry("Goossens (Willy). ", "Joseph Middeleer (1865-1939) bekend kunstschilder. ",
          "Huldenbergs Heemblad. Heemkundig tijdschrift voor Huldenberg, Loonbeek, 39, 2020, 3, pp. 200-202."),
    paragraph(run("2. Méthodologie – Methodologie")),
    entry("van de Venne (Hans). ", "Daniel van Vlierden en zijn Album amicorum. ", "Venray, s.n., 2020, 679 p."),
    paragraph(run("De Groof (Matthias). ", bold=True), run("Epilogue : Shilatembo. ", italic=True),
              run("In : De Groof (Matthias) (ed.). "), run("Lumumba in the arts. ", italic=True),
              run("Leuven, Leuven University Press, 2020, pp. 424-432.")),
    entry("Kempeneers (Paul). ", "Eigendommen van baron de Warlusel in Dormaal. ",
          "Oost-Brabant. Heemkundig Tijdschrift voor het Hageland en Omgeving, LVII, 2020, 4, pp. 67-68."),
    paragraph(run("Inhoudstafel")),
    paragraph(run("I. Bibliografieën en hulpwetenschappen\t\t3")),
]


def write_docx(path, paragraphs=PARAGRAPHS):
    document = f'<?xml version="1.0"?><w:document {W}><w:body>{"".join(paragraphs)}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
    return path


def test_reads_entries_between_the_notice_and_the_contents(tmp_path):
    records, report = load_manuscript(write_docx(tmp_path / "BGBBHB2020def.docx"))
    assert report["entries"] == 5 and report["headings"] == 3
    assert [r.id for r in records] == [f"bhb:2020-m{n}" for n in range(1, 6)]
    first = records[0]
    assert first.source == "manuscript" and first.bgb_year == 2020
    assert "unpublished-manuscript" in first.provenance.flags
    # The Dutch half of a heading in a paragraph of its own joins the French half.
    assert first.section_path == ["I. Bibliographies et sciences auxiliaires – Bibliografieën en hulpwetenschappen",
                                  "A. Bibliographies courantes – Lopende bibliografieën"]
    assert records[2].section_path[-1] == "2. Méthodologie – Methodologie"


def test_italics_set_the_title_and_keep_the_journal_whole(tmp_path):
    records, _ = load_manuscript(write_docx(tmp_path / "BGBBHB2020def.docx"))
    article = records[0]
    assert article.type == "article"
    assert article.title == "Eigendommen van baron de Warlusel in Dormaal"
    assert article.host.title == "Oost-Brabant. Heemkundig Tijdschrift voor het Hageland en Omgeving"
    assert (article.host.volume, article.host.issue, article.host.pages, article.year) == ("LVII", "4", "67-68", 2020)
    assert [p.family for p in article.persons] == ["Kempeneers"]
    commas = records[1]
    assert commas.type == "article"
    assert commas.host.title == "Huldenbergs Heemblad. Heemkundig tijdschrift voor Huldenberg, Loonbeek"
    assert commas.host.volume == "39" and commas.host.issue == "3"


def test_books_and_chapters(tmp_path):
    records, _ = load_manuscript(write_docx(tmp_path / "BGBBHB2020def.docx"))
    book = records[2]
    assert book.type == "book" and book.title == "Daniel van Vlierden en zijn Album amicorum"
    assert book.publisher.place == "Venray" and book.extent == "679 p."
    assert book.host is None
    assert [(p.family, p.given) for p in book.persons] == [("van de Venne", "Hans")]  # the particle stays
    chapter = records[3]
    assert chapter.type == "chapter" and chapter.title == "Epilogue : Shilatembo"
    assert chapter.host.title == "Lumumba in the arts" and chapter.host.pages == "424-432"


def test_the_same_text_twice_gets_two_keys(tmp_path):
    records, _ = load_manuscript(write_docx(tmp_path / "BGBBHB2020def.docx"))
    first, again = records[0].provenance.xml_id, records[4].provenance.xml_id
    assert again == f"{first}-2"


def test_year_and_newest_file_per_year(tmp_path):
    assert year_of(tmp_path / "BGBBHB2020def.docx") == 2020
    assert year_of(tmp_path / "BGB-BHB 2021 versie 3.docx") == 2021
    for name in ("BGBBHB2020.docx", "BGBBHB2020def.docx", "~$BGBBHB2021.docx", "notes.docx"):
        write_docx(tmp_path / name)
    assert [p.name for p in manuscript_paths(tmp_path)] == ["BGBBHB2020def.docx"]


def test_bold_names():
    assert bold_names("de Waha (Michel). ") == [{"family": "de Waha", "given": "Michel", "role": "author"}]
    assert [p["role"] for p in bold_names("De Groof (Matthias) (ed.), Stroo (Cyriel) (red.). ")] == ["editor", "editor"]
    assert [p["family"] for p in bold_names("Snoek (Govert) (medewerker), Hérard (Gaëlle) (collab.). ")] == ["Snoek", "Hérard"]
    assert bold_names("Redactie. ") == []
