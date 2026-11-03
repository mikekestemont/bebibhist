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
    straive: str  # the word or words as STRAIVE prints them
    persee: str  # as Persée reads them
    page: int | None  # the Persée PDF page (1-based)
    verdict: str = "undecided"  # "straive", "persee" or "undecided"
    corrected: str = ""  # the STRAIVE text with Persée's reading, in STRAIVE's typography


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
    """The words of a reading. Hyphens split words, so "Liège-Ouest" and "Liège Ouest" are the same two words."""
    return WORD.findall(text)


def key(word: str) -> str:
    """A word for comparison, without the differences that are only typography: compatibility forms (the superscript
    ᵉ of "xiiiᵉ" becomes e), look-alike letters of other scripts, accents, case and apostrophes."""
    import unicodedata

    return fold(unicodedata.normalize("NFKC", word).translate(LOOKALIKE)).replace(" ", "")


@dataclass
class Reading:
    straive: str  # the words as STRAIVE prints them, with what stands between them
    persee: list[str]  # the words as Persée reads them
    start: int  # where they stand in the STRAIVE text
    end: int


def readings(straive: str, persee: str) -> list[Reading] | None:
    """The places where the two readings disagree, one to three words on either side; None when the texts are too
    far apart to be the same entry (a segmentation fault on either side)."""
    left = list(WORD.finditer(straive))
    right = words(persee)
    matcher = SequenceMatcher(None, [key(m.group()) for m in left], [key(w) for w in right], autojunk=False)
    if matcher.ratio() < 0.8:
        return None
    found = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "replace" and i2 - i1 <= 3 and j2 - j1 <= 3:
            start, end = left[i1].start(), left[i2 - 1].end()
            found.append(Reading(straive[start:end], right[j1:j2], start, end))
    return found


def differences(straive: str, persee: str) -> list[tuple[str, str]] | None:
    """The words the two readings disagree on, as (STRAIVE, Persée) pairs."""
    found = readings(straive, persee)
    return None if found is None else [(" ".join(words(r.straive)), " ".join(r.persee)) for r in found]


def correction(reading: Reading) -> str:
    """The STRAIVE text with Persée's words, keeping STRAIVE's typography: what stands between the words, and its
    curly apostrophe."""
    wrong = words(reading.straive)
    superscript = wrong[-1].endswith("ᵉ")
    right = [re.sub(r"^([IVXLCivxlc]+)e$", r"\1ᵉ", word.replace("'", "’")) if superscript else word.replace("'", "’")
             for word in reading.persee]
    if len(wrong) == len(right):
        text, position = reading.straive, 0
        for old, new in zip(wrong, right):
            at = text.index(old, position)
            text = text[:at] + new + text[at + len(old):]
            position = at + len(new)
        return text
    return " ".join(right)


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
        return min(counts[key(word)] - own for word in words(reading)) if words(reading) else 0

    left, right = known(straive, 1), known(persee, 0)
    if left >= minimum and left >= ratio * max(right, 1):
        return "straive"
    if right >= minimum and right >= ratio * max(left, 1):
        return "persee"
    return "undecided"


def given_name_counts(texts) -> Counter:
    """How often each word is printed as a given name, in the brackets after a family name ("Mueller (Harmut)")."""
    counts: Counter = Counter()
    for text in texts:
        for inside in re.findall(r"[A-ZÀ-Þ][\w’'-]+ \(([^()]{1,40})\)", text or ""):
            counts.update(key(word) for word in words(inside))
    return counts


def plausible(reading: Reading, text: str, given_names: Counter) -> bool:
    """Whether a correction the word counts favour may be applied. Not when Persée splits a word STRAIVE prints
    whole ("Graaff", "Graaf f"); not for an abbreviation ("arr." for arrondissement); not for a word with œ or æ,
    an old spelling the print has ("œconomiques"); and a given name only becomes a word printed as a given name
    elsewhere ("Harmut" is no "Hannut")."""
    wrong = words(reading.straive)
    if len(reading.persee) > len(wrong) and key("".join(reading.persee)) == key("".join(wrong)):
        return False
    if len(wrong) == 1 and len(wrong[0]) <= 4 and text[reading.end:reading.end + 1] == ".":
        return False
    if re.search("[œæŒÆ]", reading.straive):
        return False
    before = text[:reading.start]
    if before.count("(") > before.count(")") and re.search(r"[A-ZÀ-Þ][\w’'-]+ \([^()]*$", before):
        return all(given_names[key(word)] >= 3 for word in reading.persee)
    return True


def compare(records, persee_dir: Path, counts: Counter, given_names: Counter | None = None) -> tuple[list[Difference], Counter]:
    """Every difference between the STRAIVE and Persée readings of 1960–63 and 1966–69, with a verdict."""
    given_names = given_names if given_names is not None else given_name_counts(record.printed for record in records)
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
        found_here = readings(record.printed, other[0])
        if found_here is None:
            tally["too far apart"] += 1
            continue
        tally["paired"] += 1
        tally["words"] += len(words(record.printed))
        for reading in found_here:
            left, right = " ".join(words(reading.straive)), " ".join(reading.persee)
            verdict = decide(left, right, counts)
            if verdict == "persee" and not plausible(reading, record.printed, given_names):
                verdict = "undecided"
            difference = Difference(record.id, reading.straive, right, other[1], verdict, correction(reading))
            tally[difference.verdict] += 1
            found.append(difference)
    return found, tally


def correction_rows(found: list[Difference], today: str) -> list[dict[str, str]]:
    """The differences decided for Persée as rows of ``data/curated/ocr_persee.csv`` (the columns of
    ``corrections.csv``), one per entry and wrong text."""
    rows, seen = [], set()
    for difference in found:
        if difference.verdict != "persee" or (difference.record_id, difference.straive) in seen or difference.straive == difference.corrected:
            continue
        seen.add((difference.record_id, difference.straive))
        rows.append({"id": difference.record_id, "wrong": difference.straive, "right": difference.corrected, "kind": "ocr",
                     "checked_by": "machine: Persée 1960–69 and word counts", "date": today,
                     "note": f"Persée reads {difference.persee!r}; Persée PDF page {difference.page}"})
    return rows
