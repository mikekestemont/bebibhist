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
