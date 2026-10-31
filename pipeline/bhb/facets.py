"""Coarse period facet. Keyword lists from the prototype brief, nothing finer."""

from __future__ import annotations

import re

from bhb.sections import part_kind

# Order is the order in which values are stored when several match.
# 1789 is not here: a date alone is not a period. See ``_contemporary``.
_KEYWORDS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ancient",
        re.compile(
            r"préhistoire|prehistorie|voorgeschiedenis|romaine|romeins|"
            r"mérovingien|meroving|carolingien|karoling",
            re.IGNORECASE,
        ),
    ),
    (
        "medieval",
        re.compile(
            r"principautés médiévales|middeleeuwse vorstendommen|moyen[\s-]âge|middeleeuwen",
            re.IGNORECASE,
        ),
    ),
    ("burgundian", re.compile(r"Bourgogne|Bourgondi", re.IGNORECASE)),
    (
        "early-modern",
        re.compile(
            r"Habsbourg|Habsburg|Pays-Bas espagnols|Spaanse Nederlanden|"
            r"temps modernes|Moderne Tijd|principauté de Liège|prinsbisdom Luik",
            re.IGNORECASE,
        ),
    ),
    ("contemporary", re.compile(r"contemporain|hedendaags", re.IGNORECASE)),
]

_ERA_WITH_1789 = re.compile(
    r"nos jours|tot heden|contemporain|hedendaags|eigentijds",
    re.IGNORECASE,
)
_CODE_MEDIEVAL = re.compile(r"^III\.B\.[12](?:\.|$)")
_CODE_BURGUNDIAN = re.compile(r"^III\.B\.3(?:\.|$)")


def periods_from_path(section_path: list[str]) -> list[str]:
    if not section_path:
        return []
    kind = part_kind(section_path[0])
    # The bibliography part (auxiliary sciences) has no period: it is a subject area, not a time. General works
    # span all periods ("general", shown as "Across periods"). History-by-period takes its period from the
    # headings underneath, not from the part title.
    if kind == "aux":
        return []
    if kind == "general":
        return ["general"]
    blob = " ".join(section_path)
    found = [name for name, pattern in _KEYWORDS if pattern.search(blob)]
    if "contemporary" not in found and any(_contemporary(heading) for heading in section_path):
        found.append("contemporary")
    return found


def _contemporary(heading: str) -> bool:
    """1789 counts only in the heading that also names the era, not in a date range."""
    if re.search(r"contemporain|hedendaags", heading, re.IGNORECASE):
        return True
    return "1789" in heading and _ERA_WITH_1789.search(heading) is not None


def periods_from_codes(codes: list[str]) -> list[str]:
    found: list[str] = []
    for code in codes:
        if code.startswith("I."):
            continue
        if code.startswith("II."):
            found.append("general")
        elif code.startswith("III.A"):
            found.append("ancient")
        elif _CODE_MEDIEVAL.match(code):
            found.append("medieval")
        elif _CODE_BURGUNDIAN.match(code):
            found.append("burgundian")
        elif code.startswith("III.C"):
            found.append("early-modern")
        elif code.startswith("III.D"):
            found.append("contemporary")
    return list(dict.fromkeys(found))


def assign_period(section_path: list[str], codes: list[str]) -> list[str]:
    return list(dict.fromkeys([*periods_from_path(section_path), *periods_from_codes(codes)]))
