"""Fetching records from the State Archives' catalogue, against a fake session, and parsing its display text."""

import gzip
import json

from bhb.opac_harvest import harvest, missing_hosts, parse, parse_folder


def answer(number, title="Tijdschrift voor Nederlandse Taal- en Letterkunde", note="", series=""):
    elements = [("FullMainTitle", " ".join(f"#!#Uindex04^{w.lower()}^{w}#!#" for w in title.split())),
                ("FullImprint", "Leiden : #!#Uindex08^brill^Brill#!#, 1 (1881)-"),
                ("FullCorporation", "#!#.278.11290***Uindex15$^m^Maatschappij der Nederlandse Letterkunde#!# "),
                ("FullNote", note), ("FullSeries", series),
                ("FullMaterialType", "Tijdschrift/Revue<br><br>"),
                ("FullCoverA", "MATTYPE=R!!!###!!!BIBTYPE=as!!!###!!!PUBTYPE=3")]
    body = "".join(f"<Element><Label>{k}</Label><Data><![CDATA[{v}]]></Data></Element>" for k, v in elements)
    return (f'<?xml version="1.0"?><searchRetrieveResponse><records><record><recordData><BibDocument>'
            f"<Id>2.{number}</Id><BibData>{body}</BibData></BibDocument></recordData></record></records>"
            f"</searchRetrieveResponse>")


class FakeSession:
    def __init__(self, empty_first=()):
        self.token = "t"
        self.asked = []
        self.empty_first = set(empty_first)

    def post(self, params):
        number = int(params["Request"])
        self.asked.append(number)
        if number in self.empty_first:
            self.empty_first.discard(number)
            return ""
        return answer(number) if number != 999 else '<searchRetrieveResponse><records></records></searchRetrieveResponse>'


def test_parse_strips_index_links_and_reads_the_bgb_year():
    record = parse(answer(1202178, title="Auteursherkenning met rijmwoorden", note='"BGB-BHB 2012" - Publicatie niet aanwezig',
                          series="Tijdschrift voor Nederlandse Taal- en Letterkunde, 2012, vol. 128, nr. 2, p. 135-159"))
    assert record["number"] == 1202178
    assert record["MainTitle"] == "Auteursherkenning met rijmwoorden"
    assert record["Imprint"] == "Leiden : Brill, 1 (1881)-"
    assert record["Corporation"] == "Maatschappij der Nederlandse Letterkunde"
    assert record["MaterialType"] == "Tijdschrift/Revue"
    assert record["bgb_year"] == 2012
    assert record["mattype"] == "R" and record["bibtype"] == "as"
    assert record["Series"].endswith("p. 135-159")


def test_harvest_keeps_records_skips_cached_and_retries_an_empty_answer(tmp_path):
    session = FakeSession(empty_first={2})
    waits = []
    counts = harvest([1, 2, 999], tmp_path, session, interval=5, sleep=waits.append, log=lambda *a, **k: None)
    assert counts == {"cached": 0, "fetched": 2, "empty": 1}
    assert session.asked == [1, 2, 2, 999, 999]  # an empty answer is asked once more
    assert sorted(p.name for p in tmp_path.iterdir()) == ["1.xml.gz", "2.xml.gz"]
    assert all(w >= 5 for w in waits)
    again = FakeSession()
    counts = harvest([1, 2], tmp_path, again, sleep=lambda s: None, log=lambda *a, **k: None)
    assert counts["cached"] == 2 and again.asked == []
    assert [r["number"] for r in parse_folder(tmp_path)] == [1, 2]


def test_missing_hosts(tmp_path):
    records = [{"id": "bhb:vs-1", "host": {"id": "bhb:vs-2"}}, {"id": "bhb:vs-3", "host": {"id": "bhb:vs-1"}},
               {"id": "bhb:1990-1", "host": {"id": None}}]
    path = tmp_path / "records.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    assert missing_hosts(path) == [2]
