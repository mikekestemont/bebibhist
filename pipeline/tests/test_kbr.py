"""KBR's Belgian Bibliography: names, matching and carrying names over, without the network."""

from bhb.kbr import Book, Name, _check, carry_names, match, name_fits, parse_ermes, parse_name, parse_record
from bhb.model import Person, Publisher, Record


def test_names_as_kbr_writes_them():
    name = parse_name("Duquet, Frans (1922-2013) - heemkundige")
    assert (name.family, name.given, name.dates) == ("Duquet", "Frans", "1922-2013")
    assert parse_name("Weyns, Norbertus Josephus \r\n. Directeur de la publication").given == "Norbertus Josephus"
    assert parse_name("Geluck, Philippe (1954-) - Scénariste. Illustrateur").dates == "1954-"
    assert parse_name("Bigot, Yves. Auteur de préface, introduction, etc.").given == "Yves"
    assert parse_name("Fredriks, D. M. Auteur").given == "D. M"
    assert parse_name("Persyn, Jul.").given == "Jul."
    assert parse_name("Dupuis (Marcinelle). Publisher") is None
    assert parse_name("Koen - pseudoniem. Typographe") is None


def test_initials_fit_the_written_out_name():
    assert name_fits("W.", "Walter")
    assert name_fits("M.-A.", "Maurice-Aurélien")
    assert name_fits("Jul.", "Jules")
    assert name_fits("N. I.", "Norbertus Josephus")  # the OCR reads J as I
    assert name_fits("", "Walter")
    assert not name_fits("W.", "Karel")
    assert not name_fits("M.-A.", "Maurice")


def test_contractions_are_not_written_out():
    from bhb.kbr import written_out

    assert written_out("Walter") and written_out("Jo") and written_out("Marie-Christine")
    assert not written_out("Th") and not written_out("W.") and not written_out("Jul.")


def _book(id="bhb:1990-1", title="Vilvoorde in de Tweede Wereldoorlog", family="Calderon", given="A.", year=1995, isbn=()):
    return Record(id=id, source="print-straive", bgb_year=year, type="book", title=title, year=year,
                  persons=[Person(family=family, given=given)], publisher=Publisher(name="Heemkundige Kring"), isbn=list(isbn))


def test_a_book_matches_on_title_and_author_and_takes_the_isbn():
    kbr = Book("123", "Vilvoorde in de Tweede Wereldoorlog", ["Calderon, Adelijn"], ["Heemkundige kring"], ["9072547276"], 1996)
    matches, counts = match([_book()], [kbr])
    assert [(found.number, found.basis, found.isbn) for found in matches] == [("123", "author", ["9072547276"])]


def test_another_year_or_another_number_is_no_match():
    record = _book()
    assert _check(*_target(record), Book("1", record.title, ["Calderon, Adelijn"], [], [], 2010), True) is None
    record = _book(title="Jaarboek 1991")
    assert _check(*_target(record), Book("1", "Jaarboek 1992", ["Calderon, Adelijn"], [], [], 1991), True) is None


def _target(record):
    from bhb.kbr import targets

    return (targets([record])[0],)


def test_several_editions_with_different_isbns_are_left_out():
    first = Book("1", "Vilvoorde in de Tweede Wereldoorlog", ["Calderon, Adelijn"], [], ["9072547276"], 1994)
    second = Book("2", "Vilvoorde in de Tweede Wereldoorlog", ["Calderon, Adelijn"], [], ["9789072547279"], 1997)
    matches, counts = match([_book()], [first, second])
    assert not matches and counts["several editions (left out)"] == 1


def test_a_record_and_its_ermes_details():
    record = ("<header/><metadata><oai_dc:dc><dc:title>De staten van goed / Marcel Smessaert</dc:title><dc:type>Livre</dc:type>"
              "<dc:creator>Smessaert, Marcel</dc:creator><dc:identifier>https://uurl.kbr.be/bib/42</dc:identifier>"
              "<dc:identifier>90-6569-410-2</dc:identifier><callnumber>BB A 1974 1.353</callnumber></oai_dc:dc></metadata>")
    book = parse_record(record)
    assert (book.number, book.title, book.isbn, book.shelf_year) == ("42", "De staten van goed", ["9065694102"], 1974)
    text = ('<field name="YearOfPublication">1990</field><field name="Author_xml">&lt;items&gt;&lt;item type="link"&gt;&lt;query&gt;'
            '&lt;index&gt;Authority_id_idx&lt;/index&gt;&lt;searchTerm&gt;14823345&lt;/searchTerm&gt;&lt;/query&gt;&lt;queryLabel&gt;'
            'Schwab, Ute&lt;/queryLabel&gt;&lt;/item&gt;&lt;/items&gt;</field>')
    detail = parse_ermes(text)
    assert detail.year == 1990 and [(name.family, name.given, name.kbr_id) for name in detail.names] == [("Schwab", "Ute", "14823345")]


def _entry(id, family, given, year, name_from=None, given_full=None, dates=None):
    person = Person(family=family, given=given, given_full=given_full, dates=dates, name_from=name_from)
    return Record(id=id, source="print-straive", bgb_year=year, type="article", year=year, persons=[person])


def test_a_name_is_carried_over_when_it_can_only_be_that_person():
    matched = _entry("a", "Prevenier", "W.", 1980, "kbr", "Walter", "1934-")
    other = _entry("b", "Prevenier", "W.", 1975)
    counts = carry_names([matched, other], {})
    assert other.persons[0].given_full == "Walter" and other.persons[0].name_from == "kbr-name"
    assert counts["given names written out elsewhere"] == 1


def test_an_ocr_misreading_is_no_namesake():
    matched = _entry("a", "Prevenier", "W.", 1980, "kbr", "Walter")
    misread = _entry("b", "Prevenier", "waiter", 1985)
    other = _entry("c", "Prevenier", "W.", 1990)
    carry_names([matched, misread, other], {})
    assert other.persons[0].given_full == "Walter"


def test_a_namesake_stops_the_carrying_over():
    matched = _entry("a", "Janssens", "J.", 1980, "kbr", "Jan")
    namesake = _entry("b", "Janssens", "Jozef", 1985)
    other = _entry("c", "Janssens", "J.", 1990)
    carry_names([matched, namesake, other], {})
    assert other.persons[0].given_full is None
    # A namesake known to KBR only counts too.
    other = _entry("c", "Janssens", "J.", 1990)
    carry_names([_entry("a", "Janssens", "J.", 1980, "kbr", "Jan"), other], {"janssens": [["Joris", None, None]]})
    assert other.persons[0].given_full is None


def test_no_name_after_its_bearer_died():
    matched = _entry("a", "Duquet", "F.", 1980, "kbr", "Frans", "1922-2013")
    later = _entry("b", "Duquet", "F.", 2020)
    carry_names([matched, later], {})
    assert later.persons[0].given_full is None


def test_name_class_dates():
    assert Name("Duquet", "Frans", 1922, 2013).dates == "1922-2013"
    assert Name("Duquet", "Frans").dates is None
