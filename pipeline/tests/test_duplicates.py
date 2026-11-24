from bhb.duplicates import link_duplicates
from bhb.model import Host, Person, Publisher, Record, Series


def _chapter(id, year_of_volume, given, title, isbn=(), series=None):
    return Record(
        id=id, source="print-straive", bgb_year=year_of_volume, type="chapter", title=title, year=2002,
        persons=[Person("Jacquemin", given, "author")],
        host=Host(title="Zoos humains", pages="253–258", publisher=Publisher("Paris", "La Découverte")),
        isbn=list(isbn), series=series,
    )


def test_the_same_chapter_in_two_volumes_is_one_publication():
    early = _chapter("bhb:2003-43255", 2003, "Jean-Pierre", "Les Congolais dans la Belgique ‘impériale’")
    later = _chapter("bhb:2005-50765", 2005, "J.-P.", "Les congolais dans la Belgique ‘impériale’", ["2707136387"],
                     Series("Textes à l’appui. Série Histoire contemporaine"))
    counts = link_duplicates([early, later])
    # The listing with the ISBN and the series is kept; the other points to it.
    assert later.duplicate_of is None
    assert early.duplicate_of == "bhb:2005-50765"
    assert counts["publications listed more than once"] == 1


def test_other_pages_or_another_year_stay_apart():
    one = _chapter("bhb:2003-1", 2003, "J.", "Les Congolais dans la Belgique impériale")
    other_pages = _chapter("bhb:2005-2", 2005, "J.", "Les Congolais dans la Belgique impériale")
    other_pages.host.pages = "1–10"
    other_year = _chapter("bhb:2006-3", 2006, "J.", "Les Congolais dans la Belgique impériale")
    other_year.year = 2004
    link_duplicates([one, other_pages, other_year])
    assert all(record.duplicate_of is None for record in (one, other_pages, other_year))


def test_one_volume_listing_a_notice_twice_keeps_both_classifications():
    # Guy Vanthemsche, 10 Nov 2026: his notice on Velter, BGB 2002 n° 39080 and 39810, under two headings.
    from bhb.model import Category

    def notice(id, heading, code, theme):
        return Record(
            id=id, source="print-straive", bgb_year=2002, type="chapter", year=2001, title="Velter, Georges, 1896–1979",
            persons=[Person("Vanthemsche", "Guy")], host=Host(title="Nouvelle biographie nationale", pages="384–386"),
            section_path=[heading], categories=[Category(code=code, source="crosswalk", confidence=1.0, machine=False,
                                                         primary=True)], theme=[theme], period=["contemporary"],
        )

    economic = notice("bhb:2002-39080", "Les organisations patronales", "III.D.2.b.1.", "economic")
    cultural = notice("bhb:2002-39810", "La littérature", "III.D.2.e.", "cultural")
    counts = link_duplicates([economic, cultural])
    kept, other = (economic, cultural) if cultural.duplicate_of else (cultural, economic)
    assert other.duplicate_of == kept.id and kept.duplicate_of is None
    assert {category.code for category in kept.categories} == {"III.D.2.b.1.", "III.D.2.e."}
    assert sum(category.primary for category in kept.categories) == 1
    assert set(kept.theme) == {"economic", "cultural"} and kept.period == ["contemporary"]
    assert other.section_path in kept.secondary_sections
    assert counts["chapters listed twice in one volume"] == 1


def test_an_article_reprinted_in_another_journal_stays_apart():
    first = Record(id="bhb:2006-1", source="print-straive", bgb_year=2006, type="article", year=2006,
                   title="Une manifestation à Mouscron le 7 brumaire", persons=[Person("Depauw", "Claude")],
                   host=Host(title="Mémoires de la Société d'histoire de Comines", pages="10–20"))
    second = Record(id="bhb:2007-2", source="print-straive", bgb_year=2007, type="article", year=2006,
                    title="Une manifestation à Mouscron le 7 brumaire", persons=[Person("Depauw", "Claude")],
                    host=Host(title="Le fil", pages="10–20"))
    link_duplicates([first, second])
    assert first.duplicate_of is None and second.duplicate_of is None


def test_chapters_of_a_volume_listed_twice_point_to_the_kept_listing():
    from bhb.model import Host

    first = Record(id="bhb:2003-1", source="print-straive", bgb_year=2003, type="book", year=2002,
                   title="Zoos humains : XIXe et XXe siècles", persons=[Person("Bancel", "Nicolas", "editor"), Person("Bancel", "N.", "author")])
    second = Record(id="bhb:2005-2", source="print-straive", bgb_year=2005, type="book", year=2002, isbn=["2707136387"],
                    title="Zoos humains : XIXe et XXe siècles", persons=[Person("Bancel", "Nicolas", "editor"), Person("Bancel", "N.", "author")])
    chapter = Record(id="bhb:2003-3", source="print-straive", bgb_year=2003, type="chapter", title="Les Congolais",
                     host=Host(id="bhb:2003-1"))
    counts = link_duplicates([first, second, chapter])
    assert first.duplicate_of == "bhb:2005-2"
    assert chapter.host.id == "bhb:2005-2"
    assert counts["chapters moved to the kept volume"] == 1


def test_a_printed_entry_of_2012_points_to_the_catalogues_record():
    catalogue = Record(id="bhb:vs-1202178", source="vsmart", bgb_year=2012, type="article",
                       title="Auteursherkenning met rijmwoorden in de Middelnederlandse Arthur- en Karelepiek",
                       subtitle="Eerherstel voor Icarus?", persons=[Person("Kestemont", "Mike", "author")],
                       host=Host(title="Tijdschrift voor Nederlandse Taal- en Letterkunde", pages="135-159"),
                       bhb_codes=["III.B.1.d."])
    printed = Record(id="bhb:2012-85123", source="print-pdf", bgb_year=2012, type="article",
                     title="Auteursherkenning met rijmwoorden in de Middelnederlandse Arthur- en Karelepiek : "
                           "Eerherstel voor Icarus?", persons=[Person("Kestemont", "M.", "author")],
                     host=Host(title="TNTL", pages="135-159"),
                     section_path=["III. Histoire par époques – Geschiedenis in tijdvakken"])
    only_printed = Record(id="bhb:2012-85124", source="print-pdf", bgb_year=2012, type="article",
                          title="Een titel die de catalogus niet kent", persons=[Person("Kestemont", "M.", "author")])
    other_year = Record(id="bhb:2013-91800", source="print-pdf", bgb_year=2013, type="article",
                        title=printed.title, persons=[Person("Kestemont", "M.", "author")])
    counts = link_duplicates([catalogue, printed, only_printed, other_year])
    assert printed.duplicate_of == "bhb:vs-1202178" and catalogue.duplicate_of is None
    assert only_printed.duplicate_of is None and other_year.duplicate_of is None
    assert counts["printed entries linked to their catalogue record"] == 1
    # The printed heading joins the catalogue's record.
    assert catalogue.secondary_sections == [printed.section_path]


def test_an_exact_pair_keeps_the_catalogues_record_too():
    from bhb.model import Provenance

    catalogue = Record(id="bhb:vs-1", source="vsmart", bgb_year=2010, type="book", title="Een boek over Brugge in 1900",
                       year=2010, persons=[Person("Peeters", "Jan", "author")])
    printed = Record(id="bhb:2010-70001", source="print-pdf", bgb_year=2010, type="book",
                     title="Een boek over Brugge in 1900", year=2010, persons=[Person("Peeters", "Jan", "author")],
                     isbn=["9789000000000"], publisher=Publisher("Brugge", "Uitgeverij"), extent="200 p.")
    link_duplicates([catalogue, printed])
    assert printed.duplicate_of == "bhb:vs-1" and catalogue.duplicate_of is None


def test_a_printed_entry_finds_the_catalogues_record_a_year_apart_or_with_its_author_spelled_otherwise():
    def catalogue(id, year, family, given, title):
        return Record(id=id, source="vsmart", bgb_year=year, type="article", title=title, persons=[Person(family, given, "author")])

    def printed(id, year, family, given, title):
        return Record(id=id, source="print-pdf", bgb_year=year, type="article", title=title, persons=[Person(family, given, "author")])

    zellik = catalogue("bhb:vs-1", 2014, "de Schrijver", "Albrecht", "Herinneringen aan mijn soldatentijd in Zellik")
    clusius = catalogue("bhb:vs-2", 2012, "Boutroue", "Marie-Elisabeth", "French manuscript sources on Carolus Clusius")
    other = catalogue("bhb:vs-3", 2012, "Boutroue", "Jean", "Een geheel andere studie over de Lage Landen")
    far = catalogue("bhb:vs-4", 2016, "Peeters", "An", "De restauratie van een tuin in Mons")
    entries = [
        printed("bhb:2013-1", 2013, "de Schrijver", "Albrecht", "Herinneringen aan mijn soldatentijd in Zellik"),
        printed("bhb:2012-2", 2012, "Boutrue", "Marie-Elisabeth", "French manuscript sources on Carolus Clusius"),
        printed("bhb:2012-3", 2012, "Boutrue", "Jean", "Nog een studie over de Lage Landen"),  # titles differ
        printed("bhb:2014-4", 2014, "Peeters", "An", "De restauratie van een tuin in Mons"),  # two years apart
    ]
    counts = link_duplicates([zellik, clusius, other, far, *entries])
    assert [entry.duplicate_of for entry in entries] == ["bhb:vs-1", "bhb:vs-2", None, None]
    assert counts["printed entries linked to their catalogue record"] == 2


def test_a_yearly_series_or_a_short_title_a_year_apart_is_not_paired():
    def record(id, source, year, title):
        return Record(id=id, source=source, bgb_year=year, type="article", title=title, persons=[Person("Tillie", "Paul", "author")])

    series = Record(id="bhb:vs-5", source="vsmart", bgb_year=2017, type="article",
                    title="50 jaar geleden - Groot-Poperinge in 1967", persons=[Person("Tillie", "Paul", "author")])
    preface = Record(id="bhb:vs-6", source="vsmart", bgb_year=2017, type="chapter", title="Avant-propos",
                     persons=[Person("Tillie", "Paul", "author")])
    entries = [record("bhb:2016-1", "print-pdf", 2016, "50 jaar geleden : Groot-Poperinge in 1966"),
               record("bhb:2016-2", "print-pdf", 2016, "Avant-propos")]
    link_duplicates([series, preface, *entries])
    assert [entry.duplicate_of for entry in entries] == [None, None]


def test_anonymous_entries_and_compound_names_pair_with_the_catalogue():
    from bhb.duplicates import link_print_to_catalogue
    from bhb.model import Host, Person, Provenance, Record

    def printed(n, title, persons=(), host=None, printed_text=None):
        return Record(id=f"bhb:2015-p{n}", source="print-pdf", bgb_year=2015, type="article", title=title,
                      persons=list(persons), host=Host(title=host) if host else None,
                      printed=printed_text or title, provenance=Provenance())

    def catalogue(n, title, family, host=None, given=None):
        return Record(id=f"bhb:vs-{n}", source="vsmart", bgb_year=2015, type="article", title=title,
                      persons=[Person(family=family, given=given)] if family else [], host=Host(title=host) if host else None,
                      provenance=Provenance())

    eisden = printed(1, "Herinneringen. Marieke Frensen. Eisden", host="Driemaandelijks tijdschrift",
                     printed_text="Herinneringen. Marieke Frensen. Eisden. Driemaandelijks tijdschrift, 2015, 3, pp. 4-9.")
    redactie = printed(2, "Redactie. Pro Justitia anno 1862", host="Heemkundige Kring Moerbeke",
                       printed_text="Redactie. Pro Justitia anno 1862. Heemkundige Kring Moerbeke, 2015, pp. 1-3.")
    elsewhere = printed(3, "Herinneringen aan de mijn", host="Ons Heem", printed_text="Herinneringen aan de mijn. Ons Heem, 2015.")
    years = printed(4, "1917 : het leven onder de Duitse bezetting", printed_text="1917 : het leven onder de Duitse bezetting. Gent, 2015.")
    compound = printed(5, "Monumenten getuigen, enkele beschouwingen", [Person(family="Deveen", given="Ann")])
    records = [eisden, redactie, elsewhere, years, compound,
               catalogue(1, "Herinneringen", "s.n.", "Eisden"), catalogue(2, "Pro Justitia anno 1862", "redactie", "Heemkundige Kring Moerbeke"),
               catalogue(3, "Herinneringen", "s.n.", "Eisden"), catalogue(4, "1917", "s.n."),
               catalogue(5, "Monumenten getuigen, enkele beschouwingen", "De Pauw-Deveen", given="Ann")]
    link_print_to_catalogue(records)
    assert eisden.duplicate_of == "bhb:vs-1" and redactie.duplicate_of == "bhb:vs-2"
    assert elsewhere.duplicate_of is None and years.duplicate_of is None
    assert compound.duplicate_of == "bhb:vs-5"


def test_the_third_pass_pairs_on_pages_or_a_shared_author():
    from bhb.duplicates import link_print_to_catalogue
    from bhb.model import Host, Person, Provenance, Record

    def record(id, source, kind, title, families, host=None, pages=None, subtitle=None, year=2016):
        return Record(id=id, source=source, bgb_year=2016, type=kind, title=title, subtitle=subtitle, year=year,
                      persons=[Person(family=f, role="author") for f in families],
                      host=Host(title=host, pages=pages) if host or pages else None, provenance=Provenance())

    # The catalogue names another person first (the subject, Rosseels); the pages agree.
    rosseels = record("bhb:2016-p1", "print-pdf", "chapter", "Schrijven tussen geloof en twijfel. Maria Rosseels (1916-2005)",
                      ["Swinnen"], "Een kleine literatuurgeschiedenis", "143-146")
    # No author printed, the journal's name run on into the title; the catalogue names "s.n." and the journal elsewhere.
    eisden = record("bhb:2016-p2", "print-pdf", "article", "Kroniek van een oorlog : Grand-Halleux en zijn Rue Eysden Mines. Eisden",
                    [], "Driemaandelijks tijdschrift van de VZW", "50-53")
    # A book: the authors in another order, one only in the catalogue.
    book = record("bhb:2016-p3", "print-pdf", "book", "Hemel en aarde : Religie in Vlaanderen sinds 1750", ["Hermans", "Vints"])
    # Not paired: another "Introduction" (short title, another volume), a run-on entry whose pages agree by chance,
    # a book with no author in common.
    intro = record("bhb:2016-p4", "print-pdf", "chapter", "Introduction", ["Vandervellen"], "The Golden Age", "1-4")
    run_on = record("bhb:2016-p5", "print-pdf", "article", "Portretten van een schrijverschap. Jaarboek, 2009. Dicht bij Elsschot",
                    ["Surdiacourt"], "Berichten", "39-46")
    other_book = record("bhb:2016-p6", "print-pdf", "book", "Monasterium Herkenrode 1", ["Hartmann", "Indekeu"])
    records = [rosseels, eisden, book, intro, run_on, other_book,
               record("bhb:vs-1", "vsmart", "chapter", "Schrijven tussen geloof en twijfel", ["Rosseels"], "Schrijvende vrouwen",
                      "143-146", subtitle="Maria Rosseels (1916-2005)"),
               record("bhb:vs-2", "vsmart", "article", "Kroniek van een oorlog", ["s.n."], "Eisden", "50-53",
                      subtitle="Grand-Halleux en zijn Rue Eysden Mines"),
               record("bhb:vs-3", "vsmart", "book", "Hemel en aarde", ["Vints", "Hermans"], subtitle="Religie in Vlaanderen sinds 1750"),
               record("bhb:vs-4", "vsmart", "chapter", "Introduction", ["Jones"], "Euthanasia and assisted suicide", "1-4"),
               record("bhb:vs-5", "vsmart", "article", "Dicht bij Elsschot", ["'t Hoen"], "Zuurvrij", "39-46"),
               record("bhb:vs-6", "vsmart", "book", "Monasterium Herkenrode 1", ["De Dijn", "Caluwaerts"])]
    link_print_to_catalogue(records)
    assert [r.duplicate_of for r in (rosseels, eisden, book)] == ["bhb:vs-1", "bhb:vs-2", "bhb:vs-3"]
    assert [r.duplicate_of for r in (intro, run_on, other_book)] == [None, None, None]


def test_titles_that_agree_as_well_are_decided_by_the_pages():
    from bhb.duplicates import link_print_to_catalogue
    from bhb.model import Host, Person, Provenance, Record

    def record(id, source, title, pages):
        return Record(id=id, source=source, bgb_year=2012, type="article", title=title,
                      persons=[Person(family="Keersmaekers", role="author")], host=Host(title="Het Land van Ham", pages=pages),
                      provenance=Provenance())

    printed = record("bhb:2012-88700", "print-pdf", "De Kajotters van Kwaadmechelen, dl. 2", "38-40")
    first = record("bhb:vs-1209100", "vsmart", "De Kajotters van Kwaadmechelen", "28-31")
    second = record("bhb:vs-1209109", "vsmart", "De Kajotters van Kwaadmechelen, dl. 2", "38-40")
    link_print_to_catalogue([printed, first, second])
    assert printed.duplicate_of == "bhb:vs-1209109"


def test_two_listings_whose_subtitle_was_read_once_into_the_title_are_one_publication():
    from bhb.model import Person, Record

    def book(id, year, title, subtitle=None):
        return Record(id=id, source="print-pdf", bgb_year=year, type="book", title=title, subtitle=subtitle, year=2008,
                      persons=[Person("Jappens", "Jan", "author")])

    a = book("bhb:2008-63504", 2008, "Spraakmakende stomme films uit Machelen", "de Belga Films van Hippoliet De Kempeneer")
    b = book("bhb:2008-63518", 2008, "Spraakmakende stomme films uit Machelen de Belga Films van Hippoliet De Kempeneer")
    link_duplicates([a, b])
    assert {a.duplicate_of, b.duplicate_of} - {None} in ({"bhb:2008-63504"}, {"bhb:2008-63518"})
