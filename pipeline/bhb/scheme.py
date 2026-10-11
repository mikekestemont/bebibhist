"""The modern BHB scheme and the period × theme map.

English labels are drafts. ``note`` says so. The bibliography's editor reviews them.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz.fuzz import token_set_ratio

from bhb.paths import repo_root
from bhb.textutil import fold

THEMES = (
    "reference",
    "general",
    "local",
    "political",
    "economic",
    "social",
    "religious",
    "cultural",
)

# Longest phrase first. Draft English, not a published translation.
_PHRASES: tuple[tuple[str, str], ...] = (
    ("bibliographies courantes et retrospectives a l echelon national", "current and retrospective bibliographies at national level"),
    ("bibliographies courantes et retrospectives a l echelon regional ou local", "current and retrospective bibliographies at regional or local level"),
    ("listes et tables de revues", "lists and tables of journals"),
    ("archives musees et bibliotheques", "archives, museums and libraries"),
    ("archeconomie museographie bibliotheconomie", "archive studies, museography and library economy"),
    ("archivistique museumkunde bibliotheconomie", "archive studies, museography and library economy"),
    ("inventaires guides et catalogues", "inventories, guides and catalogues"),
    ("tableaux de tri", "appraisal lists"),
    ("heraldique sigillographie numismatique paleographie diplomatique", "heraldry, sigillography, numismatics, palaeography and diplomatics"),
    ("genealogie et histoire de familles", "genealogy and family history"),
    ("travaux consacres a une famille en particulier", "works on one family"),
    ("geographie historique et cartographie", "historical geography and cartography"),
    ("histoire du langage", "history of the language"),
    ("catalogues d expositions", "exhibition catalogues"),
    ("colloques et congres", "conferences and congresses"),
    ("ouvrages collectifs", "collective works"),
    ("theorie et histoire", "theory and history"),
    ("par secteurs fonctionnels", "by subject"),
    ("a l echelon national", "at national level"),
    ("a l echelon regional et local", "at regional and local level"),
    ("a l echelon regional", "at regional level"),
    ("a l echelon local", "at local level"),
    ("histoire par epoques", "history by period"),
    ("epoque contemporaine", "contemporary period"),
    ("temps modernes", "early modern period"),
    ("principautes medievales", "medieval principalities"),
    ("vie politique", "political life"),
    ("histoire des institutions et histoire politique", "institutional and political history"),
    ("histoire politique", "political history"),
    ("evenements militaires", "military events"),
    ("operations militaires", "military operations"),
    ("vie economique", "economic life"),
    ("histoire economique", "economic history"),
    ("histoire sociale", "social history"),
    ("vie culturelle", "cultural life"),
    ("histoire culturelle", "cultural history"),
    ("histoire de la culture", "cultural history"),
    ("vie religieuse", "religious life"),
    ("travaux generaux", "general works"),
    ("etudes generales", "general studies"),
    ("generalites", "general works"),
    ("historiographie", "historiography"),
    ("methodologie", "methodology"),
    ("hommages", "festschriften"),
    ("codicologie", "codicology"),
    ("iconographie", "iconography"),
    ("folklore", "folklore"),
    ("dialectologie", "dialectology"),
    ("toponymie", "toponymy"),
    ("anthroponymie", "anthroponymy"),
    ("demographie", "demography"),
    ("archeologie", "archaeology"),
    ("enseignement", "education"),
    ("les sciences", "the sciences"),
    ("les arts", "the arts"),
    ("le droit", "law"),
    ("droit", "law"),
    ("chroniques", "chronicles"),
    ("inventaires", "inventories"),
    ("guides", "guides"),
    ("catalogues", "catalogues"),
    ("occupation", "occupation"),
    ("collaboration", "collaboration"),
    ("resistance", "resistance"),
)


@dataclass
class SchemeEntry:
    code: str
    parent: str | None
    label_fr: str
    label_nl: str
    label_en: str
    source: str
    note: str


def scheme_path() -> Path:
    return repo_root() / "data" / "curated" / "scheme.csv"


def theme_map_path() -> Path:
    return repo_root() / "data" / "curated" / "theme_map.csv"


def load_scheme(path: Path | None = None) -> dict[str, SchemeEntry]:
    entries: dict[str, SchemeEntry] = {}
    with (path or scheme_path()).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            parent = row.get("parent") or ""
            entries[row["code"]] = SchemeEntry(
                code=row["code"],
                parent=parent or None,
                label_fr=row.get("label_fr") or "",
                label_nl=row.get("label_nl") or "",
                label_en=row.get("label_en") or "",
                source=row.get("source") or "",
                note=row.get("note") or "",
            )
    return entries


def load_theme_map(path: Path | None = None) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with (path or theme_map_path()).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            prefix = (row.get("code_prefix") or "").strip()
            theme = (row.get("theme") or "").strip()
            if prefix and theme:
                rows.append((prefix, theme))
    return rows


def themes_for_code(code: str, theme_map: list[tuple[str, str]] | None = None) -> list[str]:
    """Themes of the longest matching prefix, plus ``local`` from any shorter prefix."""
    rows = theme_map if theme_map is not None else load_theme_map()
    matches = [(prefix, theme) for prefix, theme in rows if _prefix_matches(code, prefix)]
    if not matches:
        return []
    longest = max(len(prefix) for prefix, _theme in matches)
    themes = [theme for prefix, theme in matches if len(prefix) == longest]
    if any(theme == "local" for _prefix, theme in matches) and "local" not in themes:
        themes.append("local")
    return list(dict.fromkeys(themes))


def leaf_label(label: str) -> str:
    return (label or "").split("/")[-1].strip()


def themes_from_label(code: str, label_fr: str) -> list[str]:
    """Sector from the wording. Letters are not stable across periods."""
    if code == "I." or code.startswith("I."):
        return ["reference"]
    leaf = fold(leaf_label(label_fr) or label_fr)
    found: list[str] = []
    if _any(
        leaf,
        (
            "regio", "lokaal", "local", "commune", "histoire locale", "echelon regional", "echelon local",
            "brabant", "flandre", "hainaut", "namur", "luxembourg", "liege", "limbourg", "anvers",
        ),
    ):
        found.append("local")
    if code.startswith("II.C"):
        found.append("local")
    if _any(
        leaf,
        (
            "politi", "institution", "droit", "guerre", "militair", "diplomat", "dynast",
            "revolution", "occupation", "collaboration", "resistance", "parlement", "pouvoir",
            "evenement", "seigneur",
        ),
    ):
        found.append("political")
    if _any(leaf, ("econom", "commerce", "industri", "financ", "agricult", "route")):
        found.append("economic")
    if _any(leaf, ("social", "demograph", "societe", "mentalit", "ouvrier", "quotidien", "fortune", "hopital")):
        found.append("social")
    if _any(
        leaf,
        (
            "religi", "eglise", "protestant", "cathol", "jansen", "macon", "juda", "sorcell",
            "laic", "culte", "saint",
        ),
    ):
        found.append("religious")
    if _any(leaf, ("generalit", "travaux generaux", "etudes generales", "historiograph", "methodolog")):
        found.append("general")
    if _any(leaf, ("cultur", "enseign", "science", " art", "arts", "humanis", "imprimer", "lettre", "archeolog")):
        found.append("cultural")
    if found:
        return list(dict.fromkeys(found))
    if code.startswith("II.C"):
        return ["local"]
    return ["general"]


def draft_english(label_fr: str) -> str:
    """Draft English for a French scheme label. Untranslated words stay in French."""
    if not label_fr:
        return ""
    parts = [leaf_label(piece).strip() for piece in label_fr.split("/")]
    return " / ".join(_translate_piece(piece) for piece in parts if piece)


def agreement_score(heading: str, code: str, scheme: dict[str, SchemeEntry]) -> float:
    """Score against the code's leaf, or against its children's leaves when the parent has none."""
    entry = scheme.get(code)
    if entry and (entry.label_fr or entry.label_nl):
        return label_agreement(heading, entry)
    children = [item for item in scheme.values() if item.parent == code and (item.label_fr or item.label_nl)]
    if not children:
        return 0.0
    joined = SchemeEntry(
        code=code,
        parent=entry.parent if entry else None,
        label_fr=" ; ".join(leaf_label(item.label_fr) for item in children if item.label_fr),
        label_nl=" ; ".join(leaf_label(item.label_nl) for item in children if item.label_nl),
        label_en="",
        source="",
        note="",
    )
    return label_agreement(heading, joined)


def label_agreement(heading: str, entry: SchemeEntry) -> float:
    """0–100. Compares the heading with the scheme leaf, not the ancestor path."""
    scores = []
    for half, label in (
        (_french_half(heading), leaf_label(entry.label_fr)),
        (_dutch_half(heading), leaf_label(entry.label_nl)),
    ):
        if half and label:
            scores.append(token_set_ratio(fold(half), fold(label)))
    return max(scores) if scores else 0.0


def code_from_path(section_path: list[str]) -> str | None:
    tokens: list[str] = []
    for heading in section_path:
        token = _number_token(heading)
        if token:
            tokens.append(token)
    if not tokens:
        return None
    return ".".join(tokens) + "."


def truncate_code(code: str, depth: int = 4) -> str:
    parts = [part for part in code.strip(".").split(".") if part]
    if not parts:
        return code
    return ".".join(parts[:depth]) + "."


def parent_code(code: str) -> str | None:
    body = code.rstrip(".")
    if "." not in body:
        return None
    return body.rsplit(".", 1)[0] + "."


def _prefix_matches(code: str, prefix: str) -> bool:
    if code == prefix:
        return True
    return code.startswith(prefix)


def _any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _strip_number(text: str) -> str:
    text = re.sub(r"^(?:[IVX]{1,4}\.|[A-Z]\.|\d{1,2}[.)]|[a-z][.)]|\d{1,2}\))\s*", "", text)
    return re.sub(r"\(\d{1,2}\)", " ", text).strip(" .")


def _french_half(heading: str) -> str:
    return re.split(r"\s*[—–]\s*|\s+-\s+", heading, maxsplit=1)[0]


def _dutch_half(heading: str) -> str:
    parts = re.split(r"\s*[—–]\s*|\s+-\s+", heading, maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def _number_token(heading: str) -> str | None:
    match = re.match(r"^\s*([IVX]{1,4})\.?\s+\S", heading)
    if match and len(match.group(1)) > 1:
        return match.group(1)
    match = re.match(r"^\s*([A-Z])\.\s+\S", heading)
    if match:
        return match.group(1)
    match = re.match(r"^\s*(\d{1,2})\.\s+\S", heading)
    if match:
        return match.group(1)
    match = re.match(r"^\s*([a-z])\s?[.)]\s+\S", heading)
    if match:
        return match.group(1)
    match = re.match(r"^\s*(\d{1,2})\)\s+\S", heading)
    if match:
        return match.group(1) + ")"
    match = re.match(r"^\s*([ivx]{1,4})\.\s+\S", heading)
    if match:
        return match.group(1)
    # A single I. / V. / X. is a letter when the title is not a part. The part
    # titles are caught by the roman branch only when the numeral is I, II or III
    # and the heading is a part; letter I is an uppercase letter.
    match = re.match(r"^\s*([IVX])\.\s+\S", heading)
    if match:
        from bhb.sections import is_part_heading

        if is_part_heading(heading):
            return match.group(1)
        return match.group(1)
    return None


def _translate_piece(piece: str) -> str:
    folded = fold(piece)
    for source, target in _PHRASES:
        if source in folded:
            folded = folded.replace(source, target)
    # Put the glossary's capitals back approximately: the draft is lowercase
    # except we keep the original piece when nothing was translated.
    if folded == fold(piece):
        return piece
    return folded


def write_scheme_and_themes(records_path: Path | None = None) -> tuple[int, int]:
    """Seed scheme.csv from build/scheme.json and add printed codes that are missing."""
    root = repo_root()
    built = json.loads((root / "build" / "scheme.json").read_text(encoding="utf-8"))
    labels = json.loads((root / "build" / "bhb_codes.json").read_text(encoding="utf-8"))
    by_code: dict[str, dict] = {}
    for row in built:
        code = row["code"]
        names = labels.get(code, {})
        by_code[code] = {
            "code": code,
            "parent": row.get("parent") or parent_code(code) or "",
            "label_fr": names.get("label_fr") or row.get("label_fr") or "",
            "label_nl": names.get("label_nl") or row.get("label_nl") or "",
            "source": "vsmart",
        }
    if records_path and records_path.is_file():
        _add_print_codes(by_code, records_path)
    for code, row in list(by_code.items()):
        parent = parent_code(code)
        while parent:
            by_code.setdefault(
                parent,
                {"code": parent, "parent": parent_code(parent) or "", "label_fr": "", "label_nl": "", "source": "vsmart"},
            )
            parent = parent_code(parent)
    rows = []
    for code in sorted(by_code, key=_code_sort):
        row = by_code[code]
        french = row["label_fr"]
        rows.append(
            {
                "code": code,
                "parent": row["parent"],
                "label_fr": french,
                "label_nl": row["label_nl"],
                "label_en": draft_english(french),
                "source": row["source"],
                "note": "draft English label, not reviewed" if french else "no printed label on this parent",
            }
        )
    _write_csv(scheme_path(), rows, ["code", "parent", "label_fr", "label_nl", "label_en", "source", "note"])
    theme_rows = []
    for row in rows:
        for theme in themes_from_label(row["code"], row["label_fr"]):
            theme_rows.append({"code_prefix": row["code"], "theme": theme})
    _write_csv(theme_map_path(), theme_rows, ["code_prefix", "theme"])
    return len(rows), len(theme_rows)


def _add_print_codes(by_code: dict[str, dict], records_path: Path) -> None:
    import json as json_mod

    seen: dict[str, tuple[str, str]] = {}
    with records_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json_mod.loads(line)
            year = record.get("bgb_year") or 0
            if year < 1993 or year > 2008 or not str(record.get("source", "")).startswith("print"):
                continue
            path = record.get("section_path") or []
            code = code_from_path(path)
            if not code or code in by_code or code in seen:
                continue
            numbered = [heading for heading in path if _number_token(heading)]
            if not numbered:
                continue
            leaf = numbered[-1]
            seen[code] = (_strip_number(_french_half(leaf)), _strip_number(_dutch_half(leaf)))
    for code, (french, dutch) in seen.items():
        by_code[code] = {
            "code": code,
            "parent": parent_code(code) or "",
            "label_fr": french,
            "label_nl": dutch,
            "source": "print-1993+",
        }


def _code_sort(code: str) -> tuple:
    return tuple(code.strip(".").split("."))


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
