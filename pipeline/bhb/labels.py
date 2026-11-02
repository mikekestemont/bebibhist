"""Repair OCR-garbled print numbers.

Numbers increase inside one BGB year. The labels that follow the printed order are the longest run whose numbers
increase from one entry to the next (an entry inserted after printing repeats the number with a suffix: ``bis``,
``ter``, ``quater``, or a letter, ``38970a``). Every other label is a misreading ("9172" among 3171 and 3173) and is
replaced by the number after the last label in that run, when that number still fits before the next one; an
unreadable label likewise. Decisions are taken against the printed run, never against an earlier repair, so one
misreading cannot push every later number up (as "38970a" read as 38971 once shifted 409 entries of 1983 by 8).
"""

from __future__ import annotations

import re
from bisect import bisect_left

_LABEL = re.compile(r"(\d+)\s*[-.]?\s*(bis|ter|quater|[a-h])?\.?$", re.IGNORECASE)
_RANK = {"": 0, "bis": 1, "ter": 2, "quater": 3}


def split_label(raw: str) -> tuple[int | None, str]:
    match = _LABEL.fullmatch(raw.strip())
    if not match:
        return None, ""
    suffix = (match.group(2) or "").lower()
    return int(match.group(1)), suffix


def _key(number: int, suffix: str) -> tuple[int, int]:
    """Sort key: a suffixed entry comes right after its number, in suffix order."""
    return number, _RANK.get(suffix, ord(suffix[0]) - ord("a") + 1 if suffix else 0)


def _printed_run(keys: list[tuple[int, int] | None]) -> set[int]:
    """Positions of the longest strictly increasing run of keys, in order (patience sorting)."""
    tails: list[tuple[int, int]] = []
    tail_at: list[int] = []
    before: dict[int, int | None] = {}
    for index, key in enumerate(keys):
        if key is None:
            continue
        place = bisect_left(tails, key)
        before[index] = tail_at[place - 1] if place else None
        if place == len(tails):
            tails.append(key)
            tail_at.append(index)
        else:
            tails[place] = key
            tail_at[place] = index
    kept: set[int] = set()
    index = tail_at[-1] if tail_at else None
    while index is not None:
        kept.add(index)
        index = before[index]
    return kept


def repair_labels(raws: list[str]) -> list[tuple[str, bool]]:
    """Return ``(print_number, repaired)`` for each raw label, in order."""
    parsed = [split_label(raw) for raw in raws]
    keys = [_key(number, suffix) if number is not None else None for number, suffix in parsed]
    kept = _printed_run(keys)
    trusted = [parsed[index][0] if index in kept else None for index in range(len(raws))]
    repaired: list[tuple[str, bool]] = []
    previous: int | None = None
    for index, (raw, (number, suffix)) in enumerate(zip(raws, parsed)):
        if index in kept:
            repaired.append((f"{number}{suffix}", False))
            previous = number
            continue
        nxt = next((value for value in trusted[index + 1 :] if value is not None), None)
        if previous is not None and suffix:
            # A suffixed entry belongs to the number before it ("18831bis" between 15831 and 15832).
            repaired.append((f"{previous}{suffix}", True))
            continue
        if previous is not None and (nxt is None or previous + 1 < nxt):
            previous += 1
            repaired.append((str(previous), True))
            continue
        repaired.append((raw.strip() if number is None else f"{number}{suffix}", False))
    return repaired
