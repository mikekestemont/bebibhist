"""Rebuild a section path from heading numbers.

Levels come from the heading text. A roman numeral is a level-1 part only when
its text is one of the printed part titles (French or Dutch, accent-folded).
Otherwise ``I.`` is the letter I at level 2, so ``I. Brabant`` stays under the
current part. Then ``A.`` / ``B.`` > ``1.`` / ``2.`` > ``a.`` / ``a)`` >
``1)`` / ``i.``.

An unnumbered heading takes the level of the last numbered heading plus one
and replaces any unnumbered heading already at that level. Two unnumbered
themes under the same numbered parent are siblings.
"""

from __future__ import annotations

import re

from rapidfuzz.fuzz import ratio

from bhb.textutil import fold

# Printed part titles, accent-folded. A heading is a part only when every piece
# of it (French, Dutch, or the two jammed together) is one of these phrases.
PART_PHRASES = (
    "bibliographies et sciences auxiliaires",
    "bibliografieen en hulpwetenschappen",
    "travaux generaux",
    "ouvrages generaux",
    "algemene werken",
    "tijdvakoverschrijdende werken",
    "histoire par epoques",
    "histoire par epoque",
    "geschiedenis in tijdvakken",
    "generalites",
    "algemeenheden",
)

_ROMAN = re.compile(r"^([IVX]{1,4})\.\s+\S")
_ROMAN_LOOSE = re.compile(r"^([IVX]{1,4})\.?\s+\S")
_UPPER = re.compile(r"^([A-Z])\.\s+\S")
_DIGIT_DOT = re.compile(r"^(\d{1,2})\.\s+\S")
_LOWER = re.compile(r"^([a-z])\s?[.)]\s+\S")
_DIGIT_PAREN = re.compile(r"^(\d{1,2})\)\s+\S")
_LOWER_ROMAN = re.compile(r"^([ivx]{1,4})\.\s+\S")
_LEADING_NUMBER = re.compile(r"^(?:[IVX]{1,4}|\d{1,2})\.?\s+", re.IGNORECASE)
_FOOTNOTE = re.compile(r"\(\d{1,2}\)")
_POINTER = re.compile(
    r"(?:voir\s+aussi|voyez\s+aussi|zie\s+ook|(?:cfr|cf)\.?)",
    re.IGNORECASE,
)
_POINTER_NUMBER = re.compile(r"\d{3,6}(?:\s*(?:bis|ter|quater))?", re.IGNORECASE)


def is_part_heading(text: str) -> bool:
    """True when the heading is only a known part title, in either language."""
    body = _FOOTNOTE.sub(" ", text)
    body = _LEADING_NUMBER.sub("", body, count=1)
    chunks = [fold(piece) for piece in re.split(r"[—–]|-", body) if fold(piece)]
    if not chunks:
        return False
    return all(_chunk_is_only_parts(chunk) for chunk in chunks)


def part_kind(text: str) -> str | None:
    """``aux``, ``general`` or ``history`` for a part heading, else None.

    The roman numeral is not enough: part I is Généralités in the 1950s and
    Bibliographies from 1962, and part II is sometimes Histoire par époques.
    """
    if not is_part_heading(text):
        return None
    folded = fold(_LEADING_NUMBER.sub("", _FOOTNOTE.sub(" ", text), count=1))
    if "bibliograph" in folded or "bibliograf" in folded or "hulpwetenschap" in folded:
        return "aux"
    if any(
        phrase in folded
        for phrase in (
            "travaux generaux",
            "ouvrages generaux",
            "algemene werken",
            "tijdvakoverschrijdend",
            "generalites",
            "algemeenheden",
        )
    ):
        return "general"
    if "histoire par epoque" in folded or "geschiedenis in tijdvak" in folded:
        return "history"
    return None


def heading_level(text: str, stack: list[tuple[int, str]]) -> int:
    if is_part_heading(text) and (_ROMAN_LOOSE.match(text) or not stack):
        return 1
    if _ROMAN.match(text):
        return 2
    if _UPPER.match(text):
        return 2
    if _DIGIT_DOT.match(text):
        return 3
    if _LOWER.match(text):
        return 4
    if _DIGIT_PAREN.match(text):
        return 5
    if _LOWER_ROMAN.match(text):
        return 6
    numbered = [item for item in stack if _is_numbered(item[1])]
    if numbered:
        return numbered[-1][0] + 1
    return 2


def push_heading(stack: list[tuple[int, str]], text: str) -> list[tuple[int, str]]:
    level = heading_level(text, stack)
    kept = [item for item in stack if item[0] < level]
    kept.append((level, text))
    return kept


def path_of(stack: list[tuple[int, str]]) -> list[str]:
    return [text for _, text in stack]


def is_see_also_heading(text: str) -> bool:
    """A line that is only ``Voir aussi`` / ``Zie ook`` / ``Cfr.`` and the numbers it lists."""
    if not _POINTER.search(text):
        return False
    stripped = _POINTER.sub(" ", text)
    stripped = _POINTER_NUMBER.sub(" ", stripped)
    letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", stripped)
    return len(letters) < 8


def see_also_numbers(text: str) -> list[str]:
    """Print numbers listed by a see-also pointer. Empty when the line has none."""
    found: list[str] = []
    for match in _POINTER.finditer(text):
        tail = text[match.end() :]
        if "(" in text[: match.start()] and ")" in tail:
            tail = tail.split(")", 1)[0]
        for number in _POINTER_NUMBER.findall(tail):
            token = re.sub(r"\s+", "", number).lower()
            if token not in found:
                found.append(token)
    return found


def _is_numbered(text: str) -> bool:
    return bool(
        is_part_heading(text)
        or _ROMAN.match(text)
        or _UPPER.match(text)
        or _DIGIT_DOT.match(text)
        or _LOWER.match(text)
        or _DIGIT_PAREN.match(text)
        or _LOWER_ROMAN.match(text)
    )


def _chunk_is_only_parts(folded: str) -> bool:
    tokens = folded.split()
    return bool(tokens) and _cover(tokens, 0)


def _cover(tokens: list[str], start: int) -> bool:
    if start >= len(tokens):
        return True
    phrases = sorted(PART_PHRASES, key=len, reverse=True)
    for phrase in phrases:
        phrase_tokens = phrase.split()
        width = len(phrase_tokens)
        if start + width > len(tokens):
            continue
        window = tokens[start : start + width]
        if window == phrase_tokens or ratio(" ".join(window), phrase) >= 90:
            if _cover(tokens, start + width):
                return True
    return False
