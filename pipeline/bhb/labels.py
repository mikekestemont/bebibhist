"""Repair OCR-garbled print numbers.

Numbers increase inside one BGB year. A label that does not sit between its
neighbours is replaced by ``previous + 1`` when that value still fits before
the next readable label. ``bis`` / ``ter`` / ``quater`` suffixes are kept.
"""

from __future__ import annotations

import re

_LABEL = re.compile(r"(\d+)(bis|ter|quater)?$", re.IGNORECASE)


def split_label(raw: str) -> tuple[int | None, str]:
    match = _LABEL.fullmatch(raw.strip())
    if not match:
        return None, ""
    suffix = (match.group(2) or "").lower()
    return int(match.group(1)), suffix


def repair_labels(raws: list[str]) -> list[tuple[str, bool]]:
    """Return ``(print_number, repaired)`` for each raw label, in order."""
    parsed = [(*split_label(raw), raw.strip()) for raw in raws]
    repaired: list[tuple[str, bool]] = []
    previous: int | None = None
    for index, (number, suffix, raw) in enumerate(parsed):
        nxt = next(
            (
                parsed[j][0]
                for j in range(index + 1, len(parsed))
                if parsed[j][0] is not None and not parsed[j][1]
            ),
            None,
        )
        if suffix and number is not None:
            repaired.append((f"{number}{suffix}", False))
            previous = number
            continue
        if number is not None and previous is not None and nxt is not None and not (previous < number < nxt):
            candidate = previous + 1
            if nxt > candidate or nxt <= previous:
                repaired.append((str(candidate), True))
                previous = candidate
                continue
        if number is None and previous is not None:
            candidate = previous + 1
            repaired.append((str(candidate), True))
            previous = candidate
            continue
        repaired.append((raw if number is None else str(number), False))
        if number is not None:
            previous = number
    return repaired
