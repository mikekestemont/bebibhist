from bhb.model import Host, Record
from bhb.repair import Vocabulary, repair_records

TEXTS = [
    "Kaufleute und Hansekaufleute in Brügge.", "Die Kaufleute.", "Interessenkonflikte im Mittelalter.",
    "Un défi de taille.", "Le défi.", "Le défi.",
    "L'abbaye de Villers-en-Brabant.", "Villers-en-Brabant.", "Villers-en-Brabant, 1200.",
    "HOGT: Haachts oudheid- en geschiedkundig tijdschrift.", "Haachts oudheid- en geschiedkundig tijdschrift, XI.",
    "Haachts oudheid- en geschiedkundig tijdschrift, XV.",
    "Villersen-Brabant (damaged).",
    "Haachts oudheiden geschiedkundig tijdschrift (damaged).",
]


def test_split_ligatures_and_lost_hyphens_are_repaired_in_the_fields():
    vocabulary = Vocabulary.from_texts(TEXTS)
    assert vocabulary.repair("Hansekaufl eute in Brügge") == "Hansekaufleute in Brügge"
    assert vocabulary.repair("Interessenkonfl ikte") == "Interessenkonflikte"
    assert vocabulary.repair("un défi de taille") == "un défi de taille"
    assert vocabulary.repair("La ferme de Villersen-Brabant") == "La ferme de Villers-en-Brabant"
    assert vocabulary.repair("HOGT: Haachts oudheiden geschiedkundig tijdschrift") == "HOGT: Haachts oudheid- en geschiedkundig tijdschrift"


def test_the_printed_text_stays_and_a_subtitle_loses_its_leading_dash():
    printed = "Dubuisson (M.). Deux chroniques. - Villersen-Brabant et les Dunes."
    record = Record(id="bhb:2005-1", source="print-straive", bgb_year=2005, printed=printed, title="Deux chroniques",
                    subtitle="- Villersen-Brabant et les Dunes", host=Host(title="Hansekaufl eute in Brügge"))
    counts = repair_records([record], Vocabulary.from_texts(TEXTS))
    assert record.printed == printed
    assert record.subtitle == "Villers-en-Brabant et les Dunes"
    assert record.host.title == "Hansekaufleute in Brügge"
    assert "fields-repaired" in record.provenance.flags
    assert counts["records repaired"] == 1
