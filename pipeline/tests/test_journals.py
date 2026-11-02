"""One name per journal: Ibid., abbreviations, variants and ISSN anchors."""

from bhb.journals import build, is_abbreviation, resolve_ibid
from bhb.model import Host, Provenance, Record


def _article(number: str, journal: str, issn: list[str] | None = None, year: int = 1990) -> Record:
    return Record(id=f"bhb:{year}-{number}", source="print-straive", bgb_year=year, print_number=number, type="article",
                  title=f"Article {number}", host=Host(title=journal), issn=issn or [], provenance=Provenance())


def test_an_abbreviation_begins_the_words_of_the_full_title_in_order():
    assert is_abbreviation("bull du c art et h de gembloux", "bulletin du cercle art et histoire de gembloux et environs")
    assert is_abbreviation("rev b de phil et d h", "revue belge de philologie et d histoire")
    assert not is_abbreviation("rev du nord", "revue belge de philologie et d histoire")
    assert not is_abbreviation("bull", "bulletin du cercle art et histoire de gembloux")


def test_ibid_takes_the_journal_of_the_entry_printed_just_before():
    first, second = _article("100", "Biekorf"), _article("101", "Ibid.")
    book = Record(id="bhb:1990-102", source="print-straive", bgb_year=1990, print_number="102", type="book", title="Een boek", provenance=Provenance())
    chapter = Record(id="bhb:1990-103", source="print-straive", bgb_year=1990, print_number="103", type="chapter", title="Een hoofdstuk",
                     host=Host(title="Ibid."), provenance=Provenance())
    lone = _article("200", "Ibid.", year=1991)
    assert resolve_ibid([first, second, book, chapter, lone]) == 2
    assert second.host.title == "Biekorf" and "host-from-ibid" in second.provenance.flags
    assert chapter.host.title == "Een boek"
    assert lone.host.title == "Ibid."


def test_an_ibid_left_in_the_citation_gets_the_journal_issue_and_year_and_passes_it_on():
    journal = Record(id="bhb:1986-45355", source="print-straive", bgb_year=1986, print_number="45355", type="article",
                     title="Veertig jaar sociaal beleid", host=Host(title="Nieuw Ts. voor Politiek", issue="1", year="1986", pages="23–32"),
                     year=1986, provenance=Provenance())
    rezsohazy = Record(id="bhb:1986-45356", source="print-straive", bgb_year=1986, print_number="45356", type="other",
                       title="Ontwikkelingsfactoren en overheidsbeleid",
                       printed="Rezsohazy (R.). Ontwikkelingsfactoren en overheidsbeleid. Ibid., pp. 57–68.", provenance=Provenance())
    own_volume = Record(id="bhb:1986-45357", source="print-straive", bgb_year=1986, print_number="45357", type="other", title="Iets",
                        printed="X (Y.). Iets. Ibid., 235, pp. 39–41.", provenance=Provenance())
    assert resolve_ibid([journal, rezsohazy, own_volume]) == 2
    assert (rezsohazy.type, rezsohazy.year) == ("article", 1986)
    assert (rezsohazy.host.title, rezsohazy.host.issue, rezsohazy.host.pages) == ("Nieuw Ts. voor Politiek", "1", "57–68")
    assert (own_volume.host.title, own_volume.host.volume, own_volume.host.issue) == ("Nieuw Ts. voor Politiek", "235", None)


def test_an_ibid_after_a_book_is_a_chapter_of_that_book():
    book = Record(id="bhb:1975-24066", source="print-straive", bgb_year=1975, print_number="24066", type="book",
                  title="La médecine populaire", year=1975, provenance=Provenance())
    article = Record(id="bhb:1975-24067", source="print-straive", bgb_year=1975, print_number="24067", type="article",
                     title="Bases psychologiques", host=Host(title="Ibid.", pages="7–22"), provenance=Provenance())
    assert resolve_ibid([book, article]) == 1
    assert (article.type, article.host.title, article.host.year) == ("chapter", "La médecine populaire", "1975")


def test_spellings_join_by_issn_full_title_variant_and_abbreviation():
    records = [_article(str(n), "Revue du Nord", ["0035-2624", "1166-486X"]) for n in range(3)]
    records += [_article(str(10 + n), "Rev. du Nord") for n in range(2)]
    records += [_article(str(20 + n), "Biekorf") for n in range(20)]
    records += [_article(str(50 + n), "Biekorf (Brugge)") for n in range(20)]
    records += [_article(str(80 + n), "Handelingen", ["0770-0822"]) for n in range(5)]
    journals, mapping = build(records)
    assert mapping["revue du nord"] == ("issn:0035-2624", "issn")
    assert mapping["rev du nord"] == ("issn:0035-2624", "abbreviation")
    assert mapping["biekorf brugge"] == ("t:biekorf", "variant")
    assert "handelingen" not in mapping
    north = next(journal for journal in journals if journal["id"] == "issn:0035-2624")
    assert north["title"] == "Revue du Nord" and north["issn"] == "0035-2624|1166-486X" and north["articles"] == 5


def test_a_journal_is_named_by_its_lowest_issn_whatever_the_order_found():
    records = [_article(str(n), "Handelingen van het Genootschap voor Geschiedenis", ["0774-286X", "0770-0822"]) for n in range(3)]
    _, mapping = build(records)
    assert mapping["handelingen van het genootschap voor geschiedenis"] == ("issn:0770-0822", "issn")


def test_a_catalogue_note_is_left_out_of_the_journal_name():
    from bhb.journals import display_title

    assert display_title("Mémoires de la Société d'Histoire de Comines et de la région [voortgezet als = continué par] Mémoires") == \
        "Mémoires de la Société d'Histoire de Comines et de la région"
    assert display_title("Mémoires de la Société d’histoire de Comines-Warneton et de la région (Warneton)") == \
        "Mémoires de la Société d’histoire de Comines-Warneton et de la région (Warneton)"


def test_a_renamed_journal_keeps_its_old_name_for_the_years_before():
    records = [_article(str(n), "Bijdragen en mededelingen betreffende de geschiedenis der Nederlanden", ["0165-0505"], year=1975 + n)
               for n in range(20)]
    records += [_article(str(100 + n), "Bijdragen voor de geschiedenis der Nederlanden", year=1955 + n) for n in range(4)]
    records += [_article(str(200 + n), "Bijdr. Gesch. Ned.", year=1956 + n) for n in range(3)]
    records += [_article(str(300 + n), "Bijdr. en Meded. betreffende de Gesch. der Ned.", year=1980 + n) for n in range(3)]
    journals, mapping = build(records)
    predecessor = ("t:bijdragen-voor-de-geschiedenis-der-nederlanden", "predecessor")
    named = next(journal for journal in journals if journal["id"] == predecessor[0])
    assert named["title"] == "Bijdragen voor de geschiedenis der Nederlanden" and named["issn"] == ""
    assert mapping["bijdragen voor de geschiedenis der nederlanden"] == predecessor
    assert mapping["bijdr gesch ned"] == predecessor
    assert mapping["bijdr en meded betreffende de gesch der ned"] == ("issn:0165-0505", "abbreviation")
