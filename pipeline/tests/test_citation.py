"""Hand-written citations: articles, books, chapters, editors, series, cross-refs."""

from bhb.parse.citation import parse_citation


def test_article_roman_volume_and_issue():
    parsed = parse_citation(
        "Dhondt (J.). Bibliographie. Revue du Nord, XLVI, 1964, 181, pp. 253-302."
    )
    assert parsed.type == "article"
    assert parsed.persons[0]["family"] == "Dhondt"
    assert parsed.persons[0]["given"] == "J."
    assert parsed.title == "Bibliographie"
    assert parsed.host_title == "Revue du Nord"
    assert parsed.volume == "XLVI"
    assert parsed.year == 1964
    assert parsed.issue == "181"
    assert parsed.pages == "253-302"


def test_two_authors_ampersand():
    parsed = parse_citation(
        "De Wever (F.) & Vandewalle (P.). Het gebruik van de computer. Album, II, 1975, pp. 163-192."
    )
    assert [p["family"] for p in parsed.persons] == ["De Wever", "Vandewalle"]
    assert parsed.host_title == "Album"
    assert parsed.volume == "II"
    assert parsed.pages == "163-192"


def test_comma_separated_authors():
    parsed = parse_citation(
        "De Smet (Antoine), Wellens-De Donder (Liliane), Calcoen (Roger). Comité belge. "
        "Bruxelles, 1964, 18 p."
    )
    assert [p["family"] for p in parsed.persons] == ["De Smet", "Wellens-De Donder", "Calcoen"]
    assert parsed.type == "book"
    assert parsed.title == "Comité belge"
    assert parsed.place == "Bruxelles"
    assert parsed.year == 1964
    assert parsed.extent == "18 p."


def test_book_with_format_and_price():
    parsed = parse_citation(
        "Van Hove (Julien). Répertoire des périodiques. Bruxelles, Librairie encyclopédique, "
        "1964, 8°, 223 p., 300 F.B."
    )
    assert parsed.type == "book"
    assert parsed.title == "Répertoire des périodiques"
    assert parsed.place == "Bruxelles"
    assert parsed.publisher == "Librairie encyclopédique"
    assert parsed.year == 1964
    assert parsed.extent == "223 p."
    assert parsed.pages is None


def test_book_series_paren():
    parsed = parse_citation(
        "Mairesse (François). Mariemont, capitale du don. Morlanwelz, Musée Royal, 2007, "
        "125 p. (Monographies du musée, 15)."
    )
    assert parsed.type == "book"
    assert parsed.title == "Mariemont, capitale du don"
    assert parsed.series_title == "Monographies du musée"
    assert parsed.series_number == "15"
    assert parsed.extent == "125 p."


def test_series_number_without_comma():
    parsed = parse_citation(
        "Balle (Arthur). La toponymie de Soumoy. Cerfontaine, Musée de Cerfontaine, 2007, "
        "17 p. (Cahiers d'Entre-Sambre-et-Meuse 155)."
    )
    assert parsed.series_number == "155"
    assert "Entre-Sambre" in parsed.series_title


def test_chapter_in_colon():
    parsed = parse_citation(
        "Nys (Liesbet). Het museum en zijn publiek. In: De Jong (L.). Het Koninklijk Museum, pp. 131-142."
    )
    assert parsed.type == "chapter"
    assert parsed.persons[0]["family"] == "Nys"
    assert parsed.title == "Het museum en zijn publiek"
    assert parsed.host_title == "Het Koninklijk Museum"
    assert parsed.pages == "131-142"
    assert all(p["family"] != "De Jong" for p in parsed.persons)


def test_chapter_with_publisher():
    parsed = parse_citation(
        "Nys (Liesbet). Het collectief genot. In: Smit (Christianne). Fatsoenlijk vertier. "
        "Amsterdam, Bert Bakker, 2008, pp. 63-87."
    )
    assert parsed.type == "chapter"
    assert parsed.title == "Het collectief genot"
    assert parsed.host_title == "Fatsoenlijk vertier"
    assert parsed.place == "Amsterdam"
    assert parsed.publisher == "Bert Bakker"
    assert parsed.year == 2008
    assert parsed.pages == "63-87"


def test_editor_marker():
    parsed = parse_citation(
        "Colin (G.) (éd.). Bibliographie du livre. Bruxelles, Bibliothèque, 1964, 20 p."
    )
    assert parsed.persons[0]["role"] == "editor"
    assert parsed.type == "book"


def test_dutch_editor_and_dir():
    red = parse_citation("Janssens (W.) (red.). Titel. Gent, Academia, 1990, 100 p.")
    assert red.persons[0]["role"] == "editor"
    directed = parse_citation("Maes (P.) (dir.). Titel. Liège, Université, 1980, 50 p.")
    assert directed.persons[0]["role"] == "editor"
    assert directed.place == "Liège"


def test_et_al():
    parsed = parse_citation("Ketgens (Eric) e.a. De collectie. Antwerpen, Museum, 2007, 80 p.")
    assert parsed.persons[0]["family"] == "Ketgens"
    assert "et-al" in parsed.flags
    assert parsed.type == "book"
    assert parsed.title == "De collectie"


def test_bracket_translation():
    parsed = parse_citation(
        "Bockstaele (Paul). Bibliografie van de geschiedenis der wetenschappen. "
        "[Bibliographie de l'histoire des sciences]. Scientiarum Historia, 5, 1963, pp. 178-194."
    )
    assert parsed.title == "Bibliografie van de geschiedenis der wetenschappen"
    assert parsed.title_translated == "Bibliographie de l'histoire des sciences"
    assert parsed.host_title == "Scientiarum Historia"
    assert parsed.volume == "5"
    assert parsed.year == 1963
    assert parsed.pages == "178-194"


def test_annotation_after_pages():
    parsed = parse_citation(
        "Thibaut (Gérard). Notes héraldiques. Hémecht, XXVII, 1975, 4, pp. 523-526. "
        "— Concerne les familles de Beausaint."
    )
    assert parsed.note.startswith("Concerne")
    assert parsed.host_title == "Hémecht"
    assert parsed.volume == "XXVII"
    assert parsed.issue == "4"
    assert "Concerne" not in (parsed.title or "")


def test_parallel_title_dash_stays_in_title():
    parsed = parse_citation(
        "Van Hove (Julien). Répertoire des périodiques. 3e supplément — Repertorium van de "
        "tijdschriften. Bruxelles, Librairie encyclopédique, 1964, 223 p."
    )
    assert parsed.type == "book"
    assert "Repertorium" in parsed.title
    assert parsed.note is None
    assert parsed.publisher == "Librairie encyclopédique"


def test_cross_ref_removed_from_citation():
    parsed = parse_citation(
        "Van den Heuvel (R.). Een merkwaardige figuur. Bull. van de Pharmacie, 1975, 50, "
        "pp. 9-40. [Voir n° 22721]."
    )
    assert parsed.cross_refs == [(None, "22721")]
    assert "22721" not in (parsed.title or "")
    assert parsed.issue == "50"
    assert parsed.pages == "9-40"
    assert parsed.is_cross_listing is False


def test_cross_ref_zie_and_voir_without_brackets():
    dutch = parse_citation(
        "Janssen (P.). Een studie. Tijdschrift voor geschiedenis, 10, 1990, pp. 1-10. Zie nr. 12345."
    )
    assert dutch.cross_refs == [(None, "12345")]
    french = parse_citation("Dupuis (A.). Une note. Revue, IV, 1955, pp. 1-2. Voir n° 999.")
    assert french.cross_refs == [(None, "999")]
    assert french.volume == "IV"


def test_cross_listing_stub():
    parsed = parse_citation("[Voir n° 22721].")
    assert parsed.is_cross_listing is True
    assert parsed.cross_refs == [(None, "22721")]


def test_multiple_page_ranges():
    parsed = parse_citation(
        "Bockstaele (Paul). Bibliografie. Scientiarum Historia, 5, 1963, "
        "pp. 178-194 ; 6, 1964, pp. 97-107."
    )
    assert "178-194" in parsed.pages
    assert "97-107" in parsed.pages
    assert "multi-range" in parsed.flags
    assert parsed.year == 1963
    assert parsed.volume == "5"


def test_unknown_place_publisher_date():
    parsed = parse_citation("Anon (A.). Titel. s.l., s.n., s.d., 10 p.")
    assert parsed.type == "book"
    assert parsed.title == "Titel"
    assert parsed.place is None
    assert parsed.publisher is None
    assert parsed.year is None
    assert parsed.extent == "10 p."
    assert {"s.l.", "s.n.", "s.d."} <= set(parsed.flags)


def test_issue_without_roman_volume():
    parsed = parse_citation(
        "Docquier (Gilles). La collection d'autographes. Histoire du fonds. "
        "Les cahiers de Mariemont, 2008, 37-38, pp. 7-33."
    )
    assert parsed.title == "La collection d'autographes. Histoire du fonds"
    assert parsed.host_title == "Les cahiers de Mariemont"
    assert parsed.year == 2008
    assert parsed.issue == "37-38"
    assert parsed.volume is None
    assert parsed.pages == "7-33"


def test_en_dash_pages_and_particle_surname():
    parsed = parse_citation(
        "Van Eenoo (Romain). Bibliografie. Belgisch tijdschrift, LXXXIV, 2006, pp. 1–270."
    )
    assert parsed.persons[0]["family"] == "Van Eenoo"
    assert parsed.pages == "1–270"
    assert parsed.volume == "LXXXIV"


def test_hyphenated_surname():
    parsed = parse_citation(
        "Haesenne-Peremans (N.). Une étude. Revue, II, 1975, pp. 10-20."
    )
    assert parsed.persons[0]["family"] == "Haesenne-Peremans"
    assert parsed.volume == "II"


def test_volume_and_issue():
    parsed = parse_citation(
        "Merenne (E.). Bibliographie des articles. Ardenne et Famenne, VII, 1964, 1-2, pp. 42-60."
    )
    assert parsed.volume == "VII"
    assert parsed.year == 1964
    assert parsed.issue == "1-2"
    assert parsed.host_title == "Ardenne et Famenne"


def test_ibid_host():
    parsed = parse_citation("Genicot (L.). Droit et principauté. Ibid., pp. 307-335.")
    assert parsed.host_title == "Ibid"
    assert "ibid-host" in parsed.flags
    assert parsed.pages == "307-335"
    assert parsed.year is None


def test_single_p_pages():
    parsed = parse_citation("Broucke (Roger). De Faluintjes. Tijdschrift, 2009, p. 286-289.")
    assert parsed.pages == "286-289"
    assert parsed.year == 2009


def test_no_personal_author_book():
    parsed = parse_citation(
        "Bibliotheca Belgica. Bruxelles, Culture et civilisation, 1975, 500 p."
    )
    assert parsed.persons == []
    assert parsed.type == "book"
    assert parsed.title == "Bibliotheca Belgica"
    assert parsed.publisher == "Culture et civilisation"


def test_sp_extent():
    parsed = parse_citation("Y (B.). Online only. Gent, Universiteit, 2015, s.p.")
    assert parsed.extent == "s.p."
    assert "s.p." in parsed.flags
    assert parsed.year == 2015
    assert parsed.place == "Gent"


def test_chapter_etal_in_host():
    parsed = parse_citation(
        "Floré (Freddy). Bokrijk. In: Tollebeek (J.) e.a. België, een parcours. pp. 402-413."
    )
    assert parsed.type == "chapter"
    assert parsed.persons[0]["family"] == "Floré"
    assert parsed.host_title == "België, een parcours"
    assert parsed.pages == "402-413"


def test_abbreviated_host_kept():
    parsed = parse_citation(
        "Art (J.). Bibliographie de l'histoire de Belgique, 1974. "
        "Rev. b. de Philologie et d'Hist., LIII, 1975, pp. 1150-1283."
    )
    assert parsed.host_title.startswith("Rev.")
    assert parsed.volume == "LIII"
    assert parsed.year == 1975
    assert "1974" in parsed.title


def test_multi_word_particle_surname():
    parsed = parse_citation(
        "Le Bailly de Tilleghem (Serge). Musée des Beaux-Arts. Tournai, ASBL Tourisme, 2008, 80 p."
    )
    assert parsed.persons[0]["family"] == "Le Bailly de Tilleghem"
    assert parsed.persons[0]["given"] == "Serge"
    assert parsed.type == "book"


def test_cfr_inside_brackets_with_degree_sign():
    parsed = parse_citation(
        "Puissant (Jean). Le Grand-Hornu. Revue, X, 2008, pp. 1-4. [Cfr. n° 60552]."
    )
    assert parsed.cross_refs == [(None, "60552")]
    assert parsed.pages == "1-4"
