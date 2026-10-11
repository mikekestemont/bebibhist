"""Whitespace, superscripts and small string helpers shared by the adapters."""

from __future__ import annotations

import re
import unicodedata

# Printed superscripts. The vendor encodes "XVI<sup>e</sup> siècle"; we keep a
# single visible character so the citation still reads as printed.
_SUP = {
    "e": "ᵉ",
    "er": "ᵉʳ",
    "re": "ʳᵉ",
    "ere": "ᵉʳᵉ",
    "me": "ᵐᵉ",
    "o": "ᵒ",
    "a": "ᵃ",
    "n": "ⁿ",
    "s": "ˢ",
    "r": "ʳ",
    "d": "ᵈ",
    "t": "ᵗ",
    "m": "ᵐ",
    "i": "ⁱ",
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
}


def fold(text: str) -> str:
    """Accent-folded lowercase, punctuation turned into spaces. For matching, not display."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.lower().replace("œ", "oe").replace("æ", "ae")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def squash(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00a0", " ").replace("\u2009", " ").replace("\u202f", " ")
    return re.sub(r"\s+", " ", text).strip()


def superscript(text: str) -> str:
    key = re.sub(r"\s+", "", text)
    if key in _SUP:
        return _SUP[key]
    return "".join(_SUP.get(ch, ch) for ch in key)


def clean_heading(text: str) -> str:
    """Heading as printed, without footnote markers such as ``(1)``."""
    text = squash(text)
    text = re.sub(r"\s*\(\d{1,2}\)\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -—")
    return text
