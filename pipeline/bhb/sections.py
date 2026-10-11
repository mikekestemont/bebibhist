"""Rebuild a section path from heading numbers.

``<ref-list>`` nesting in the STRAIVE files is not reliable. Levels come from
the heading text: ``I.`` / ``II.`` > ``A.`` / ``B.`` > ``1.`` / ``2.`` >
``a.`` / ``a)`` > ``1)`` / ``i.``. An unnumbered heading becomes a child of
the previous numbered one. A single letter that continues the previous
capital (``H.`` then ``I.``) is that letter, not a roman numeral.
"""

from __future__ import annotations

import re

_ROMAN = re.compile(r"^([IVX]{1,4})\.\s+\S")
_UPPER = re.compile(r"^([A-Z])\.\s+\S")
_DIGIT_DOT = re.compile(r"^(\d{1,2})\.\s+\S")
_LOWER = re.compile(r"^([a-z])\s?[.)]\s+\S")
_DIGIT_PAREN = re.compile(r"^(\d{1,2})\)\s+\S")
_LOWER_ROMAN = re.compile(r"^([ivx]{1,4})\.\s+\S")


def heading_level(text: str, stack: list[tuple[int, str]]) -> int:
    if match := _ROMAN.match(text):
        token = match.group(1)
        if len(token) == 1:
            letters = [heading for level, heading in stack if level == 2]
            if letters and (prev := _UPPER.match(letters[-1])):
                if ord(token) == ord(prev.group(1)) + 1:
                    return 2
        return 1
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
    if stack:
        return stack[-1][0] + 1
    return 1


def push_heading(stack: list[tuple[int, str]], text: str) -> list[tuple[int, str]]:
    level = heading_level(text, stack)
    kept = [item for item in stack if item[0] < level]
    kept.append((level, text))
    return kept


def path_of(stack: list[tuple[int, str]]) -> list[str]:
    return [text for _, text in stack]
