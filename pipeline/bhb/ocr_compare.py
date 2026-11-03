"""Two digitisations of the same printed entries: STRAIVE (1952–63, 1966–2007) and Persée (1960–69), compared.

The Persée PDF of 1960–69 is converted per year (``bhb.ingest.persee_pdf``) and its entries are paired with the
STRAIVE entries of the same year by print number. Neither reading is the truth: where they agree, a word is
almost certainly as printed (two OCR engines seldom make the same error); where they differ, the word that occurs
elsewhere in the bibliography wins over one that does not, and the rest stays undecided, for the page image.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from bhb.textutil import fold

WORD = re.compile(r"[^\W\d_](?:[\w’']*[^\W\d_])?")


@dataclass
class Difference:
    record_id: str
    straive: str  # the word or words as STRAIVE reads them
    persee: str  # as Persée reads them
    page: int | None  # the Persée PDF page (1-based)
    verdict: str = "undecided"  # "straive", "persee" or "undecided"


def persee_entries(path: Path) -> dict[str, tuple[str, int | None]]:
    """Print number → (citation text, PDF page) of a converted Persée year."""
    import html

    text = path.read_text(encoding="utf-8")
    found = {}
    for match in re.finditer(r'<ref id="[^"]*" specific-use="pdf-page:(\d+)[^"]*">\s*<label>([^<]+)</label>\s*'
                             r"<mixed-citation[^>]*>(.*?)</mixed-citation>", text, re.S):
        found[match.group(2).strip()] = (re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", match.group(3)))).strip(),
                                         int(match.group(1)))
    return found


# Letters of other scripts that OCR puts for Latin ones (a Greek capital nu for N).
LOOKALIKE = str.maketrans("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧаеорсух", "ABEZHIKMNOPTYXaeopcyx")


def words(text: str) -> list[str]:
    """The words of a reading, after the differences that are only typography: compatibility forms (the superscript
    ᵉ of "xiiiᵉ" becomes e), look-alike letters of other scripts, and hyphens, which split words."""
    import unicodedata

    text = unicodedata.normalize("NFKC", text).translate(LOOKALIKE)
    return WORD.findall(re.sub(r"[-‐–]", " ", text))


def key(word: str) -> str:
    """A word for comparison: folded (accents, case and apostrophes aside)."""
    return fold(word).replace(" ", "")


def differences(straive: str, persee: str) -> list[tuple[str, str]] | None:
    """The words the two readings disagree on, as (STRAIVE, Persée) pairs of one to three words each; None when the
    texts are too far apart to be the same entry (a segmentation fault on either side)."""
    left, right = words(straive), words(persee)
    matcher = SequenceMatcher(None, [key(w) for w in left], [key(w) for w in right], autojunk=False)
    if matcher.ratio() < 0.8:
        return None
    pairs = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "replace" and i2 - i1 <= 3 and j2 - j1 <= 3:
            pairs.append((" ".join(left[i1:i2]), " ".join(right[j1:j2])))
    return pairs


def vocabulary(texts) -> Counter:
    """How often each folded word occurs in the bibliography."""
    counts: Counter = Counter()
    for text in texts:
        counts.update(key(word) for word in words(text or ""))
    return counts


def decide(straive: str, persee: str, counts: Counter, minimum: int = 3, ratio: int = 20) -> str:
    """The reading whose words occur elsewhere in the bibliography, when the other's do not (or far less often).
    STRAIVE's own occurrence is in the counts; it is taken off."""
    def known(reading: str, own: int) -> int:
        return min(counts[key(word)] - own for word in reading.split()) if reading else 0

    left, right = known(straive, 1), known(persee, 0)
    if left >= minimum and left >= ratio * max(right, 1):
        return "straive"
    if right >= minimum and right >= ratio * max(left, 1):
        return "persee"
    return "undecided"


def compare(records, persee_dir: Path, counts: Counter) -> tuple[list[Difference], Counter]:
    """Every difference between the STRAIVE and Persée readings of 1960–63 and 1966–69, with a verdict."""
    tally: Counter = Counter()
    found: list[Difference] = []
    by_year: dict[int, dict] = {}
    for record in records:
        if record.source != "print-straive" or not record.print_number or not record.printed:
            continue
        year = record.bgb_year
        if year not in by_year:
            path = persee_dir / f"BGB_{year}.xml"
            by_year[year] = persee_entries(path) if path.is_file() else {}
        other = by_year[year].get(record.print_number)
        if not by_year[year]:
            continue
        if other is None:
            tally["not in Persée"] += 1
            continue
        pairs = differences(record.printed, other[0])
        if pairs is None:
            tally["too far apart"] += 1
            continue
        tally["paired"] += 1
        tally["words"] += len(words(record.printed))
        for left, right in pairs:
            difference = Difference(record.id, left, right, other[1], decide(left, right, counts))
            tally[difference.verdict] += 1
            found.append(difference)
    return found, tally
