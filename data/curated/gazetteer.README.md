# gazetteer.csv

Belgian municipalities and their sections (former municipalities), one row per NIS code (`nis`), at three levels:
`area` (the country, regions, provinces and arrondissements; codes ending in 000), `municipality` and `section`, with the Wikidata item, labels in French, Dutch, German and English,
and coordinates (`lon`, `lat`, WGS 84).

Source: Wikidata, every item with property P1567 (NIS/INS code), queried on 31 October 2026. Wikidata is CC0.
Ten items (Charleroi, Bornem, Koekelberg, Zottegem, Saint-Ghislain, Bouillon …) carry their name only as a
language-neutral label (`mul`); it fills their empty language columns.

It resolves the place names of the printed place indexes (1993–2007) to one place each, across languages
(Bruxelles / Brussel, Gand / Gent), and gives the map its coordinates. Regions, countries and places abroad are
not in it yet; those names are kept as they are printed.
