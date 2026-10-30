"""The BHB scheme and its facets as SKOS (Turtle), written from the curated CSV files.

Three concept schemes: the BHB codes, the periods and the themes. A code combines a period and a subject
area (III.D.2.a is "contemporary" and "institutions and politics"), so it gets a ``skos:broadMatch`` to
each facet value it implies. Links to outside vocabularies (PeriodO, Wikidata) are added to the facet
values later, from one curated file; see ``docs/FACET_PROPOSAL.md``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from bhb.facets import periods_from_codes
from bhb.paths import repo_root
from bhb.scheme import SchemeEntry, load_scheme, load_theme_map, themes_for_code

BASE = "https://mikekestemont.github.io/bebibhist/vocab/"
_DRAFT_NOTE = "English label is a draft, not reviewed."


@dataclass
class FacetValue:
    facet: str
    value: str
    labels: dict[str, str]
    note: str


def facets_path() -> Path:
    return repo_root() / "data" / "curated" / "facets.csv"


def load_facets(path: Path | None = None) -> list[FacetValue]:
    with (path or facets_path()).open(encoding="utf-8", newline="") as handle:
        return [
            FacetValue(
                facet=row["facet"],
                value=row["value"],
                labels={lang: row[f"label_{lang}"] for lang in ("fr", "nl", "en") if row.get(f"label_{lang}")},
                note=row.get("note") or "",
            )
            for row in csv.DictReader(handle)
        ]


def uri(kind: str, key: str) -> str:
    return f"<{BASE}{kind}/{key.rstrip('.')}>"


def write_skos(
    path: Path,
    scheme: dict[str, SchemeEntry] | None = None,
    theme_map: list[tuple[str, str]] | None = None,
    facets: list[FacetValue] | None = None,
) -> dict[str, int]:
    scheme = scheme if scheme is not None else load_scheme()
    theme_map = theme_map if theme_map is not None else load_theme_map()
    facets = facets if facets is not None else load_facets()
    # A value with a note starting "not a period" is a part of the bibliography, not a period: no link to it.
    linkable = {(value.facet, value.value) for value in facets if not value.note.startswith("not a ")}
    lines = [
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "",
        f"{uri('scheme', 'bhb')} a skos:ConceptScheme ;",
        '    dcterms:title "Bibliographie de l\'Histoire de Belgique — classement"@fr, "Bibliografie van de Geschiedenis van België — indeling"@nl ;',
        '    dcterms:license <https://creativecommons.org/licenses/by-nc/4.0/> .',
        "",
    ]
    for facet, title in (("period", "periods"), ("theme", "themes")):
        lines += [f"{uri(facet, title)} a skos:ConceptScheme ;", f'    dcterms:title "BHB {title}"@en .', ""]
    counts = {"codes": 0, "periods": 0, "themes": 0, "facet_links": 0}
    for value in facets:
        lines.append(f"{uri(value.facet, value.value)} a skos:Concept ;")
        lines.append(f"    skos:inScheme {uri(value.facet, value.facet + 's')} ;")
        lines.append(f"    skos:topConceptOf {uri(value.facet, value.facet + 's')} ;")
        lines.append(f"    skos:notation {_literal(value.value)} ;")
        if value.note:
            lines.append(f"    skos:scopeNote {_literal(value.note, 'en')} ;")
        lines.append("    " + " ;\n    ".join(f"skos:prefLabel {_literal(label, lang)}" for lang, label in value.labels.items()) + " .")
        lines.append("")
        counts[value.facet + "s"] += 1
    for code, entry in sorted(scheme.items()):
        triples = [f"skos:inScheme {uri('scheme', 'bhb')}", f"skos:notation {_literal(code)}"]
        if entry.parent and entry.parent in scheme:
            triples.append(f"skos:broader {uri('scheme', entry.parent)}")
        else:
            triples.append(f"skos:topConceptOf {uri('scheme', 'bhb')}")
        for lang in ("fr", "nl", "en"):
            label = _last_part(getattr(entry, f"label_{lang}"))
            if label:
                triples.append(f"skos:prefLabel {_literal(label, lang)}")
        if entry.label_en:
            triples.append(f"skos:editorialNote {_literal(_DRAFT_NOTE, 'en')}")
        links = [("period", value) for value in periods_from_codes([code])]
        links += [("theme", value) for value in themes_for_code(code, theme_map)]
        for facet, value in dict.fromkeys(links):
            if (facet, value) in linkable:
                triples.append(f"skos:broadMatch {uri(facet, value)}")
                counts["facet_links"] += 1
        lines.append(f"{uri('scheme', code)} a skos:Concept ;\n    " + " ;\n    ".join(triples) + " .")
        lines.append("")
        counts["codes"] += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return counts


def _last_part(label: str) -> str:
    """A code's label is its whole path ("Histoire par époques / … / Histoire culturelle"); the concept is the last part."""
    return label.split(" / ")[-1].strip() if label else ""


def _literal(text: str, lang: str | None = None) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"@{lang}' if lang else f'"{escaped}"'
