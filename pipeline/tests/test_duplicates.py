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


def test_other_pages_another_year_or_one_volume_stay_apart():
    one = _chapter("bhb:2003-1", 2003, "J.", "Les Congolais dans la Belgique impériale")
    other_pages = _chapter("bhb:2005-2", 2005, "J.", "Les Congolais dans la Belgique impériale")
    other_pages.host.pages = "1–10"
    other_year = _chapter("bhb:2006-3", 2006, "J.", "Les Congolais dans la Belgique impériale")
    other_year.year = 2004
    same_volume = _chapter("bhb:2003-4", 2003, "J.", "Les Congolais dans la Belgique impériale")
    link_duplicates([one, other_pages, other_year, same_volume])
    assert all(record.duplicate_of is None for record in (one, other_pages, other_year, same_volume))


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
