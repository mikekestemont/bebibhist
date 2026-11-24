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
    records = [_article(str(n), "Revue du Nord", ["1166-486X", "0035-2624"]) for n in range(3)]
    _, mapping = build(records)
    assert mapping["revue du nord"] == ("issn:0035-2624", "issn")


def test_two_journals_with_articles_of_their_own_are_not_joined_by_one_article_with_both_numbers():
    records = [_article(str(n), "Handelingen van het Genootschap voor Geschiedenis te Brugge", ["0770-0822"]) for n in range(5)]
    records += [_article(str(10 + n), "Handelingen der Maatschappij voor Geschiedenis en Oudheidkunde te Gent", ["0774-286X"]) for n in range(5)]
    records.append(_article("20", "Handelingen der Maatschappij voor Geschiedenis en Oudheidkunde te Gent", ["0774-286X", "0770-0822"]))
    records += [_article(str(30 + n), "Revue du Nord", ["0035-2624"]) for n in range(3)]
    records.append(_article("40", "Revue du Nord", ["0035-2624", "1166-486X"]))  # an online number of its own only: joined
    journals, mapping = build(records)
    assert mapping["handelingen der maatschappij voor geschiedenis en oudheidkunde te gent"] == ("issn:0774-286X", "issn")
    assert mapping["handelingen van het genootschap voor geschiedenis te brugge"] == ("issn:0770-0822", "issn")
    assert next(j for j in journals if j["id"] == "issn:0035-2624")["issn"] == "0035-2624|1166-486X"


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


def test_one_ocr_slip_does_not_make_a_journal_name_an_abbreviation():
    records = [_article(str(n), "La Vie Wallonne") for n in range(30)] + [_article("99", "La. Vie wallonne")]
    _, mapping = build(records)
    assert mapping["la vie wallonne"] == ("t:la-vie-wallonne", "full")


def test_a_journal_keeps_its_id_when_another_spelling_becomes_its_name():
    from collections import Counter

    from bhb.journals import keep_ids

    records = [_article(str(n), "L’Intermédiaire") for n in range(20)]
    records += [_article(str(100 + n), "L’Intermédiaire des généalogistes") for n in range(16)]
    journals, mapping = build(records)
    assert mapping["l intermediaire des genealogistes"][0] == "t:l-intermediaire"
    count = Counter({"l intermediaire": 20, "l intermediaire des genealogistes": 16})
    previous = {"l intermediaire des genealogistes": "t:l-intermediaire-des-genealogistes"}
    assert keep_ids(journals, mapping, count, previous) == 1
    assert mapping["l intermediaire"][0] == "t:l-intermediaire-des-genealogistes"
    assert [journal["id"] for journal in journals] == ["t:l-intermediaire-des-genealogistes"]


def test_spellings_that_differ_only_in_small_words_are_one_journal_and_keep_its_abbreviations():
    records = [_article(str(n), "Bulletin du Comité flamand de France") for n in range(12)]
    records += [_article(str(20 + n), "Bulletin Comité flamand de France") for n in range(6)]
    records += [_article(str(40 + n), "Bull. du comité flamand de France") for n in range(3)]
    journals, mapping = build(records)
    assert mapping["bulletin du comite flamand de france"] == ("t:bulletin-du-comite-flamand-de-france", "full")
    assert mapping["bulletin comite flamand de france"] == ("t:bulletin-du-comite-flamand-de-france", "full")
    assert mapping["bull du comite flamand de france"] == ("t:bulletin-du-comite-flamand-de-france", "abbreviation")
    assert [journal["articles"] for journal in journals] == [21]


def test_together_below_the_threshold_small_word_forms_are_no_journal():
    records = [_article(str(n), "Archief- en bibliotheekwezen in België") for n in range(8)]
    records += [_article(str(20 + n), "Archief- et bibliotheekwezen in België") for n in range(6)]
    assert build(records)[1] == {}


def test_an_abbreviation_fitting_two_journals_goes_to_the_one_it_covers_word_for_word():
    records = [_article(str(n), "Bulletin de la Commission royale des monuments et des sites") for n in range(20)]
    records += [_article(str(30 + n), "Bulletin de la Commission royale des monuments, sites et fouilles") for n in range(20)]
    records += [_article(str(60 + n), "Bull. de la Comm. r. des monuments et des sites") for n in range(3)]
    records += [_article(str(70 + n), "Bull. de la Comm. r. des monuments") for n in range(2)]
    _, mapping = build(records)
    assert mapping["bull de la comm r des monuments et des sites"][0] == "t:bulletin-de-la-commission-royale-des-monuments-et-des-sites"
    assert "bull de la comm r des monuments" not in mapping  # fits both, covers neither


def test_the_other_forms_of_a_variant_title_go_with_it():
    records = [_article(str(n), "L’Intermédiaire") for n in range(20)]
    records += [_article(str(100 + n), "L’Intermédiaire des généalogistes") for n in range(16)]
    records += [_article(str(200 + n), "Intermédiaire des généalogistes") for n in range(2)]
    journals, mapping = build(records)
    assert mapping["intermediaire des genealogistes"][0] == mapping["l intermediaire des genealogistes"][0] == "t:l-intermediaire"
    assert len(journals) == 1


def test_a_renamed_journal_with_a_new_issn_stays_apart_from_its_predecessor(monkeypatch):
    from bhb import journals

    monkeypatch.setattr(journals, "load_successions", lambda path=None: [
        {"successor": "issn:1572-1701", "renamed_in": "2004", "predecessor_id": "issn:0303-9935",
         "predecessor_title": "Tijdschrift voor sociale geschiedenis", "note": ""}])
    old = [_article(str(n), "Tijdschrift voor sociale geschiedenis (Amsterdam)", ["0303-9935"], 2000) for n in range(5)]
    new = [_article(str(n), "Tijdschrift voor sociale en economische geschiedenis", ["2468-9068", "1572-1701"], 2010) for n in range(10, 18)]
    # Crossref lists the old number too on two articles of the renamed journal, one of them with all three.
    both = [_article("30", "Tijdschrift voor sociale en economische geschiedenis", ["2468-9068", "1572-1701", "0303-9935"], 2005),
            _article("31", "Tijdschrift voor sociale geschiedenis (Amsterdam)", ["1572-1701", "0303-9935"], 2003)]
    rows, mapping = build(old + new + both)
    by_id = {row["id"]: row for row in rows}
    assert by_id["issn:1572-1701"]["issn"] == "1572-1701|2468-9068"
    assert by_id["issn:0303-9935"]["issn"] == "0303-9935"
    assert by_id["issn:0303-9935"]["title"] == "Tijdschrift voor sociale geschiedenis"
    assert mapping["tijdschrift voor sociale en economische geschiedenis"][0] == "issn:1572-1701"
    assert mapping["tijdschrift voor sociale geschiedenis amsterdam"][0] == "issn:0303-9935"


def test_the_successor_keeps_its_online_number_whatever_the_order_of_the_articles(monkeypatch):
    from bhb import journals

    monkeypatch.setattr(journals, "load_successions", lambda path=None: [
        {"successor": "issn:1572-1701", "renamed_in": "2004", "predecessor_id": "issn:0303-9935",
         "predecessor_title": "Tijdschrift voor sociale geschiedenis", "note": ""}])
    tseg = "Tijdschrift voor sociale en economische geschiedenis"
    first = [_article("1", tseg, ["2468-9068", "0303-9935"], 2005), _article("2", tseg, ["2468-9068", "0303-9935"], 2006),
             _article("3", tseg, ["2468-9068", "1572-1701", "0303-9935"], 2007)]
    rest = [_article(str(n), tseg, ["1572-1701", "2468-9068"], 2010) for n in range(10, 15)]
    old = [_article(str(n), "Tijdschrift voor sociale geschiedenis", ["0303-9935"], 1990) for n in range(20, 25)]
    rows, _ = build(first + rest + old)
    assert {row["id"]: row["issn"] for row in rows} == {"issn:1572-1701": "1572-1701|2468-9068", "issn:0303-9935": "0303-9935"}


def test_the_successions_file_keeps_tseg_apart():
    from bhb.journals import load_successions

    rows = {(row["predecessor_id"], row["successor"]) for row in load_successions()}
    assert ("issn:0303-9935", "issn:1572-1701") in rows


def test_a_title_set_with_a_full_stop_is_not_read_as_abbreviated():
    from collections import Counter

    from bhb.journals import _abbreviated

    faro = Counter({"Faro / Tijdschrift over cultureel erfgoed": 209, "Faro. Tijdschrift over cultureel erfgoed": 36})
    assert not _abbreviated("Faro. Tijdschrift over cultureel erfgoed", faro)
    vieux = Counter({"Bull. Soc. R. Le Vieux-Liège": 40})
    assert _abbreviated("Bull. Soc. R. Le Vieux-Liège", vieux)
    assert not _abbreviated("Faro / Tijdschrift over cultureel erfgoed", faro)


def _host_article(n, host):
    from bhb.model import Host, Record

    return Record(id=f"bhb:2000-{n}", source="print-straive", bgb_year=2000, type="article", title=f"Titel {n}",
                  host=Host(title=host))


def test_a_journal_title_plus_a_place_joins_the_journal_and_a_previous_spelling_keeps_its_journal(tmp_path):
    import csv

    from bhb.journals import apply_journals

    records = [_host_article(n, "Molenecho’s") for n in range(20)] + [_host_article(100 + n, "Molenecho’s (Zulte)") for n in range(3)]
    records += [_host_article(200 + n, "Curia Arduennae") for n in range(14)]
    with (tmp_path / "journals.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "title", "issn", "spellings", "articles"])
        writer.writerow(["t:curia-arduennae", "Curia Arduennae", "", "1", "15"])
    with (tmp_path / "journal_spellings.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["spelling", "journal", "rule", "articles"])
        writer.writerow(["curia arduennae", "t:curia-arduennae", "full", "15"])
    apply_journals(records, tmp_path)
    assert records[0].journal_id and records[20].journal_id == records[0].journal_id
    assert records[-1].journal_id == "t:curia-arduennae"
    assert "t:curia-arduennae" in (tmp_path / "journals.csv").read_text(encoding="utf-8")
