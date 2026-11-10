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
