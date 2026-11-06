"""OCR misreadings of person names, found by machine (plan §4f, point 13).

A family name is taken for a misreading of another when all of these hold:

- it is printed in one entry only (a printed volume; the V-Smart catalogue is typed), and KBR's Belgian
  Bibliography has no author of that name;
- it differs from a name printed in at least three entries, and known to KBR, only as OCR misreads print: letters
  of the same shape ("Huybrecbts", "Grauweis", "Meeuseu"), "rn" or "ni" for "m" ("Beterarns"), or a space inside a
  word ("Lindem ans"); never a particle written apart or together ("Du Chesne", "Vander Made"), which are spellings;
- exactly one such name fits, and the given names agree (the same initial, the same name when both are written out).

On a sample of 50 about 47 were right. The rows go to ``data/curated/ocr_names.csv`` with the kind ``name``: the
person's name is corrected, the printed citation stays as printed, and the entry is flagged as corrected by machine.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from bhb.textutil import fold

CHECKED_BY = "machine: name spellings and KBR authors"
# Letters an OCR engine takes for one another in these volumes.
_SHAPES = {frozenset(pair) for pair in ("ce", "eo", "co", "il", "it", "lt", "nu", "uv", "bh", "hn", "ft", "mn", "ij", "vy")}
_JOINED = (("rn", "m"), ("ni", "m"), ("in", "m"), ("cl", "d"), ("li", "h"), ("vv", "w"), ("ii", "n"))
_PARTICLES = {"de", "der", "den", "van", "vande", "vander", "vanden", "du", "le", "la", "von", "ten", "ter", "d", "l"}
_FREQUENT = 3


def kbr_families(folder: Path) -> set[str]:
    """The folded family names of every person among the harvested KBR records' creators."""
    from bhb.kbr import books, parse_name

    found: set[str] = set()
    for book in books(folder):
        for creator in book.creators:
            if name := parse_name(creator):
                found.add(fold(name.family))
    return found


def misread(rare: str, good: str) -> bool:
    """True when the folded name ``rare`` is ``good`` as an OCR engine would misread it."""
    rare_words, good_words = rare.split(" "), good.split(" ")
    joined_rare, joined_good = rare.replace(" ", ""), good.replace(" ", "")
    if joined_rare == joined_good:
        # A space inside a word, not between a particle and the name.
        return len(rare_words) > len(good_words) and not any(word in _PARTICLES for word in rare_words) and rare_words[-1] not in good_words
    if [word for word in rare_words if word in _PARTICLES] != [word for word in good_words if word in _PARTICLES]:
        return False
    if any(wrong in joined_rare and joined_rare.replace(wrong, right) == joined_good for wrong, right in _JOINED):
        return True
    if len(joined_rare) != len(joined_good):
        return False
    differ = [(a, b) for a, b in zip(joined_rare, joined_good) if a != b]
    return 1 <= len(differ) <= 2 and all(frozenset(pair) in _SHAPES for pair in differ)


def _givens_agree(one: str, other: str) -> bool:
    a, b = fold(one).replace(".", " ").split(), fold(other).replace(".", " ").split()
    if not a or not b or a[0][:1] != b[0][:1]:
        return False
    return len(a[0]) == 1 or len(b[0]) == 1 or a[0] == b[0]


def _right_spelling(wrong: str, spellings: Counter) -> str:
    """The frequent name as printed most often; for a letter misread in place, the printed form with those letters
    replaced, so its capitals and particles stay as printed ("De Scbaepdrijver" → "De Schaepdrijver")."""
    usual = spellings.most_common(1)[0][0]
    if len(usual) != len(wrong) or usual.count(" ") != wrong.count(" "):
        return usual
    return "".join(good if bad.lower() != good.lower() else bad for bad, good in zip(wrong, usual))


def proposals(records, known: set[str], today: str) -> list[dict[str, str]]:
    """Rows for ``data/curated/ocr_names.csv``, one per misread name."""
    count: Counter = Counter()
    first: dict[str, tuple[str, str, str]] = {}
    spellings: dict[str, Counter] = defaultdict(Counter)
    givens: dict[str, set[str]] = defaultdict(set)
    for record in records:
        for person in record.persons:
            family = person.family or ""
            if len(family) < 4:
                continue
            key = fold(family)
            count[key] += 1
            spellings[key][family] += 1
            givens[key].add(person.given or "")
            first.setdefault(key, (record.id, record.source, person.given or ""))
    frequent: dict[str, list[str]] = defaultdict(list)
    for key, n in count.items():
        if n >= _FREQUENT and key in known:
            frequent[key.replace(" ", "")[:1]].append(key)
    rows = []
    for key, n in count.items():
        record_id, source, given = first[key]
        wrong = spellings[key].most_common(1)[0][0]
        if n != 1 or source == "vsmart" or key in known or re.search(r"[\[\]()]", wrong):
            continue
        fits = [
            other
            for other in frequent[key.replace(" ", "")[:1]]
            if abs(len(other.replace(" ", "")) - len(key.replace(" ", ""))) <= 1 and misread(key, other)
        ]
        if len(fits) != 1 or not any(_givens_agree(given, other) for other in givens[fits[0]]):
            continue
        right = _right_spelling(wrong, spellings[fits[0]])
        rows.append({
            "id": record_id,
            "wrong": wrong,
            "right": right,
            "kind": "name",
            "checked_by": CHECKED_BY,
            "date": today,
            "note": f"'{wrong}' printed once and unknown to KBR; '{right}' in {count[fits[0]]} entries and in KBR",
        })
    return sorted(rows, key=lambda row: row["id"])
