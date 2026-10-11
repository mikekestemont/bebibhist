"""Coarse period facet. Keyword lists from the prototype brief, nothing finer."""

from __future__ import annotations

import re

# Order is the order in which values are stored when several match.
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
    ("contemporary", re.compile(r"contemporaine|hedendaags|1789", re.IGNORECASE)),
]

_PART_I = re.compile(r"^\s*I\.\s")
_PART_II = re.compile(r"^\s*II\.\s")
_CODE_MEDIEVAL = re.compile(r"^III\.B\.[12](?:\.|$)")
_CODE_BURGUNDIAN = re.compile(r"^III\.B\.3(?:\.|$)")


def periods_from_path(section_path: list[str]) -> list[str]:
    if not section_path:
        return []
    head = section_path[0]
    if _PART_I.match(head):
        return ["aux"]
    if _PART_II.match(head):
        return ["general"]
    blob = " ".join(section_path)
    return [name for name, pattern in _KEYWORDS if pattern.search(blob)]


def periods_from_codes(codes: list[str]) -> list[str]:
    found: list[str] = []
    for code in codes:
        if code.startswith("I."):
            found.append("aux")
        elif code.startswith("II."):
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
