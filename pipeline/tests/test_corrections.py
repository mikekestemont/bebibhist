"""Hand corrections: an OCR error is corrected everywhere, a printer's error only in the parsed fields."""

from bhb.corrections import apply_corrections
from bhb.model import Person, Provenance, Record


def _zumkir() -> Record:
    printed = "Zuznkir (A.). Tableau politique de l’arrondissement de Verviers sous le suffrage censitaire (1830–93)."
    return Record(id="bhb:1952-3797", source="print-straive", bgb_year=1952, printed=printed,
                  title="Tableau politique de l’arrondissement de Verviers", persons=[Person("Zuznkir", "A.", "author")],
                  provenance=Provenance())


def test_an_ocr_error_is_corrected_in_the_citation_and_the_name():
    record = _zumkir()
    assert apply_corrections([record], [{"id": record.id, "wrong": "Zuznkir", "right": "Zumkir", "kind": "ocr"}]) == 1
    assert record.printed.startswith("Zumkir (A.).") and record.persons[0].family == "Zumkir"
    assert "corrected-ocr" in record.provenance.flags


def test_a_printers_error_stays_in_the_citation():
    record = _zumkir()
    assert apply_corrections([record], [{"id": record.id, "wrong": "Zuznkir", "right": "Zumkir", "kind": "print"}]) == 1
    assert record.printed.startswith("Zuznkir (A.).") and record.persons[0].family == "Zumkir"


def test_a_row_the_entry_no_longer_matches_is_not_applied():
    record = _zumkir()
    rows = [{"id": record.id, "wrong": "Seivias", "right": "Scivias", "kind": "ocr"},
            {"id": "bhb:1900-1", "wrong": "a", "right": "b", "kind": "ocr"}]
    assert apply_corrections([record], rows) == 0
    assert record.provenance.flags == []


def test_a_machine_correction_replaces_whole_words_only_and_is_flagged():
    from bhb.corrections import apply_corrections
    from bhb.model import Record

    record = Record(id="bhb:1962-4453", source="print-straive", bgb_year=1962, printed="Michel (J.). Over hel kasteel", title="Over hel kasteel")
    rows = [{"id": "bhb:1962-4453", "wrong": "hel", "right": "het", "kind": "ocr", "checked_by": "machine: Persée 1960–69 and word counts"}]
    assert apply_corrections([record], rows) == 1
    assert record.printed == "Michel (J.). Over het kasteel" and record.title == "Over het kasteel"
    assert "corrected-ocr-machine" in record.provenance.flags


def test_a_type_row_changes_the_kind_of_publication_only():
    record = _zumkir()
    record.type = "article"
    assert apply_corrections([record], [{"id": record.id, "wrong": "article", "right": "chapter", "kind": "type"}]) == 1
    assert record.type == "chapter" and record.title.startswith("Tableau politique")
    # Another type than the one the row expects, or no known type, leaves it.
    assert apply_corrections([record], [{"id": record.id, "wrong": "article", "right": "chapter", "kind": "type"}]) == 0
    assert apply_corrections([record], [{"id": record.id, "wrong": "chapter", "right": "poem", "kind": "type"}]) == 0
