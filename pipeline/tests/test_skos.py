"""The SKOS export: codes nest by parent and link to the period and theme they combine."""

from pathlib import Path

from bhb.scheme import SchemeEntry
from bhb.skos import FacetValue, write_skos


def _entry(code: str, parent: str | None, fr: str, en: str = "") -> SchemeEntry:
    return SchemeEntry(code=code, parent=parent, label_fr=fr, label_nl="", label_en=en, source="vsmart", note="")


def test_a_code_is_narrower_than_its_period_and_theme(tmp_path: Path):
    scheme = {
        "III.D.": _entry("III.D.", None, "Histoire par époques / Epoque contemporaine"),
        "III.D.2.a.": _entry(
            "III.D.2.a.",
            "III.D.",
            "Histoire par époques / Epoque contemporaine / Histoire des institutions et histoire politique",
            "history by period / contemporary period / institutional and political history",
        ),
        "I.A.": _entry("I.A.", None, "Bibliographies"),
    }
    facets = [
        FacetValue("period", "contemporary", {"fr": "Époque contemporaine", "nl": "Hedendaagse tijd"}, ""),
        FacetValue("period", "aux", {"fr": "Sciences auxiliaires"}, "not a period: the bibliography part"),
        FacetValue("theme", "political", {"fr": "Institutions, politique"}, ""),
        FacetValue("theme", "reference", {"fr": "Bibliographies"}, ""),
    ]
    out = tmp_path / "bhb.ttl"
    counts = write_skos(out, scheme, [("III.D.2.a.", "political"), ("I.", "reference")], facets)
    text = out.read_text(encoding="utf-8")
    code = text[text.index("vocab/scheme/III.D.2.a> a skos:Concept") :].split("\n\n")[0]
    assert "skos:broader <https://mikekestemont.github.io/bebibhist/vocab/scheme/III.D>" in code
    assert "skos:broadMatch <https://mikekestemont.github.io/bebibhist/vocab/period/contemporary>" in code
    assert "skos:broadMatch <https://mikekestemont.github.io/bebibhist/vocab/theme/political>" in code
    assert 'skos:prefLabel "Histoire des institutions et histoire politique"@fr' in code
    assert "skos:editorialNote" in code
    # Auxiliary sciences is a part of the bibliography, not a period: no period link.
    bibliography = text[text.index("vocab/scheme/I.A> a skos:Concept") :].split("\n\n")[0]
    assert "period/aux" not in bibliography
    assert "theme/reference" in bibliography
    assert counts == {"codes": 3, "periods": 2, "themes": 2, "facet_links": 4}
