"""Language of publication, suggested from the title (plan §5b).

No source gives a language: the printed volumes do not, and the State Archives' export has no UNIMARC 101 field. So a
local, open language identifier (Lingua, Apache 2.0; no API) reads the title and subtitle, and every value is a
machine value, stored in ``language_suggested`` (ISO 639-1, ``la`` for Latin) and shown as suggested.

Two kinds of second title must not be confused:

- **A translation by the bibliography.** Until the 1980s the volumes print a French translation of a Dutch title
  in square brackets ("De oudste kruisweg te Gent [Le plus ancien chemin de la croix à Gand]"), kept in
  ``title_translated``. It is the editors' gloss, not part of the publication, so it never adds a language.
- **A bilingual publication.** A title printed in two languages ("Catalogus Collectie Frank Brangwyn. Catalogue
  Frank Brangwyn collection"), or a parallel title catalogued from the item itself (UNIMARC 200d in the State
  Archives' export, also kept in ``title_translated``). Then both languages are given, the main title's first, and
  the entry is flagged ``language-bilingual``.

A title with too few words of its own (names, places and dates: "Damme in 1923", "Félix Van Bever (1854–1917)")
says nothing reliable. Such an article takes its journal's language where that journal publishes in one language
only (flag ``language-from-journal``); otherwise the entry gets no language.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

# The languages of the bibliography. Afrikaans, Norwegian and the like are left out on purpose: in the sample they
# were only ever Dutch titles in older spelling, or names, so they would only take votes from the right answer.
CORE = ("nl", "fr", "en", "de", "la")
OTHER = ("it", "es", "pt", "ro", "pl", "cs", "sv", "da", "hu", "ru", "el")

# Read but never given as a language of publication (Mike, 9 Nov 2026): a title read as Latin was as often a Dutch or
# French title with a Latin name or quotation ("Lambertus Lombardus pictor eburonensis: biografie") as a Latin one
# (an edition, "Cartularium Affligemense"), and publications written in Latin are very rare here. Such a title gets no
# language from its title; an article then takes its journal's language, as a title of names does.
NOT_ASSIGNED = {"la"}

# A main title needs at least this many words of its own (not names) and this confidence; a language outside CORE
# needs a longer title and a clear lead over the next one (Spanish over Portuguese). A segment of a bilingual title
# needs a strong reading on its own.
MIN_WORDS = 2
MIN_CONFIDENCE = 0.5
OTHER_WORDS = 3
OTHER_CONFIDENCE = 0.5
OTHER_LEAD = 2.0
SEGMENT_WORDS = 3
SEGMENT_CONFIDENCE = 0.7
# Lingua takes Latinate English and French ("International bibliography of historical demography") for Latin; a
# Latin title has none of the other languages' function words, and needs this confidence.
LATIN_CONFIDENCE = 0.7
# Within a title, a Latin part ("Rev. belge de numismatique et de sigillographie") needs more; so does a rarer
# language in a title with a function word of the usual ones.
SEGMENT_LATIN = 0.9
# Each language of a bilingual title must hold at least this share of the letters, and at least SEGMENT_RATIO of
# the largest language's: a translation is about as long as what it translates, while a quotation used as a title
# or the name of an archive series is short. A title in four languages gives each about a fifth.
SEGMENT_SHARE = 0.15
SEGMENT_RATIO = 0.5
# The parts outvote the reading of the whole title when they cover this share of it.
SEGMENT_COVER = 0.75
# A journal lends its language when this many of its entries have one, nearly all the same; a collected volume
# when at least two of its other chapters have one and all agree.
JOURNAL_ENTRIES = 10
JOURNAL_SHARE = 0.9
VOLUME_ENTRIES = 2

_QUOTED = re.compile(r"«[^»]*»|“[^”]*”|„[^“”\"]*[“”\"]|‘[^’]*’(?!\w)|(?<!\w)'[^']+'(?!\w)|\"[^\"]*\"")
_BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]")
# Roman numerals; an ending ("XVIᵉ", "17de") only after I, V or X, since "Le", "De", "Ce" and "Die" also fit.
_ROMAN = re.compile(r"\b(?:[IVXLCDM]*[IVX][IVXLCDM]*(?:e|ᵉ|er|es|de|ste|th|ème)|[IVXLCDM]+)\b(?!['’])")
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
# Where a title in two languages turns from one to the other: " / ", " = ", a full stop after a word, a colon.
_SEGMENT = re.compile(r"\s+[/=|]\s+|(?<=[^\s.]{3})\.\s+(?=[^\W\d_])|\s*:\s+|\s+[–—-]\s+")


def clean(text: str) -> str:
    """The words a title says in its own language: without quoted titles, words in brackets, numbers and roman
    numerals. A title that is all quotation keeps its words."""
    text = text.replace("­", "")
    unquoted = _QUOTED.sub(" ", text)
    if own_words(unquoted) >= MIN_WORDS or (letters(unquoted) and own_words(unquoted) >= own_words(text)):
        text = unquoted
    text = _BRACKETED.sub(" ", text)
    text = _ROMAN.sub(" ", text)
    text = re.sub(r"\d+", " ", text)
    return re.sub(r"\s+", " ", text).strip(" .,:;-–—")


# Function words that belong to one language of the bibliography only ("de", "en", "in" and "et" are shared, so
# they count as words of the title but not as a vote). Latin is left to the identifier.
FUNCTION_WORDS = {
    "nl": {"het", "een", "van", "voor", "met", "naar", "bij", "uit", "tot", "op", "te", "door", "ten", "ter", "aan",
           "onder", "als", "zijn", "haar", "hun", "tussen", "na", "wat", "hoe", "deze", "dit"},
    "fr": {"le", "les", "des", "du", "une", "un", "pour", "sur", "dans", "aux", "au", "à", "par", "entre", "chez",
           "son", "sa", "ses", "leur", "leurs", "ce", "cette", "ces", "est", "l", "d", "qu"},
    "en": {"the", "of", "and", "for", "with", "from", "to", "on", "between", "its", "their", "by", "into", "or", "not"},
    "de": {"der", "die", "das", "und", "im", "zur", "zum", "von", "mit", "über", "dem", "ein", "eine", "für", "auf",
           "aus", "bei", "zwischen", "einer", "eines", "vom"},
    # Words of one of the rarer languages only, so that a Spanish title read as Latin by a hair ("Interiorización
    # religiosa y propaganda hagiographica en los Paises Bajos …") is outvoted (Sébastien, 9 Nov 2026).
    "es": {"los", "las", "y", "sus", "como"},
    "it": {"della", "delle", "degli", "dei", "nel", "nella", "nelle", "negli", "alla", "alle", "gli", "dello", "sulla"},
    "pt": {"dos", "das", "uma", "não", "às"},
}
_SHARED = {"de", "en", "in", "et", "la", "a", "al", "el", "il", "ad", "cum", "per"}
_ALL_FUNCTION = set().union(*FUNCTION_WORDS.values()) | _SHARED


def own_words(text: str) -> int:
    """Words of two letters or more that are not names: lowercase words, and function words that open the title
    or a part of it ("Het", "Les"). They tell a language apart; names and places ("Félix Van Bever") do not."""
    return sum(1 for word in _words(text) if len(word) > 1 and (word[0].islower() or word.lower() in _ALL_FUNCTION))


# A capitalised word opens the title or a part of it when nothing but punctuation comes before it.
_OPENS = re.compile(r"(?:^|[.:;!?—–(«“‘'\"]\s*|\s[-/=]\s*)$")


def _words(text: str) -> list[str]:
    """The words of a title, elisions split ("l’église" gives "l" and "église"); a capitalised word inside the
    title is left out when it is a function word, since there it belongs to a name ("Van Bever", "De Smet")."""
    words = []
    for match in _WORD.finditer(text):
        for index, part in enumerate(re.split(r"['’]", match.group())):
            if not part:
                continue
            inside = index > 0 or not _OPENS.search(text[: match.start()])
            if part[0].isupper() and part.lower() in _ALL_FUNCTION and inside and not part.isupper():
                continue
            words.append(part)
    return words


# Particles of names ("… de Anton van Dyck", "… Johann von Böhmen") are not words of the title's language.
_PARTICLES = {"van", "der", "den", "von", "vom", "zu", "zum", "zur", "ten", "ter", "du", "des", "le", "la", "op"}


def votes(text: str) -> Counter[str]:
    """Function words per language, leaving out particles between two capitalised words."""
    words = _words(text)
    tally: Counter[str] = Counter()
    for index, word in enumerate(words):
        lower = word.lower()
        # "Bibliografie van Bredene" opens with a noun, not a given name, so the first word does not make a name.
        if lower in _PARTICLES and word.islower() and 1 < index < len(words) - 1 and words[index - 1][0].isupper() \
                and words[index + 1][0].isupper():
            continue
        tally.update(language for language, vocabulary in FUNCTION_WORDS.items() if lower in vocabulary)
    return tally


def segments(text: str) -> list[str]:
    return [part for part in (piece.strip() for piece in _SEGMENT.split(text)) if part]


def letters(text: str) -> int:
    return sum(1 for char in text if char.isalpha())


@dataclass
class Reading:
    language: str | None
    confidence: float
    words: int
    sure: bool = False
    # Function words of other languages than the one read.
    against: int = 0


def decide(ranked: list[tuple[str, float]], text: str) -> Reading:
    """One language for a cleaned title, from the identifier's ranking (code, confidence) and the function words.

    The identifier decides when the title has words of its own and it is fairly sure, unless two or more function
    words of another language say otherwise. A short title it is unsure of still gets a language when its function
    words point to one that the identifier ranks first or second ("Le Fort d'Embourg", "The Rise of Fiscal
    States"). A language outside CORE needs a longer title and a clear lead; Latin needs a title without function
    words of the other languages."""
    words = own_words(text)
    tally = votes(text)
    (voted, count), (_, runner_up) = (tally.most_common(2) + [(None, 0), (None, 0)])[:2]
    if not text or not ranked:
        return Reading(None, 0.0, words)
    confidence = dict(ranked)
    (code, value), second = ranked[0], ranked[1][1] if len(ranked) > 1 else 0.0
    if code == "la":
        allowed = value >= LATIN_CONFIDENCE and not tally
    elif code in CORE:
        allowed = True
    else:
        allowed = value >= OTHER_CONFIDENCE and value >= OTHER_LEAD * second and words >= OTHER_WORDS and (
            not (set(tally) - {code}) or value >= SEGMENT_LATIN)
    contradicted = count >= 2 and voted != code and not tally[code]
    def reading(language: str, sure: bool) -> Reading:
        return Reading(language, confidence[language], words, sure, sum(tally.values()) - tally[language])

    if allowed and words >= MIN_WORDS and value >= MIN_CONFIDENCE and not contradicted:
        return reading(code, True)
    top_two = {item for item, _ in ranked[:2]}
    if voted in top_two and count >= 2 and count >= 2 * runner_up:
        return reading(voted, True)
    if voted == code and not runner_up:
        return reading(code, True)
    return reading(code, False)


class Identifier:
    """Lingua over the bibliography's languages, built once (the models take a few seconds to load)."""

    def __init__(self) -> None:
        from lingua import IsoCode639_1, LanguageDetectorBuilder, Language

        languages = [Language.from_iso_code_639_1(getattr(IsoCode639_1, code.upper())) for code in CORE + OTHER]
        self._detector = LanguageDetectorBuilder.from_languages(*languages).with_preloaded_language_models().build()

    def rank(self, texts: list[str]) -> list[list[tuple[str, float]]]:
        values = self._detector.compute_language_confidence_values_in_parallel(texts)
        return [[(item.language.iso_code_639_1.name.lower(), item.value) for item in ranked] for ranked in values]

    def read(self, texts: list[str]) -> list[Reading]:
        cleaned = [clean(text) for text in texts]
        return [decide(ranked, text) for text, ranked in zip(cleaned, self.rank(cleaned))]


def main_title(record) -> str:
    parts = [record.title or ""]
    if record.subtitle and record.subtitle not in parts[0]:
        parts.append(record.subtitle)
    return ". ".join(part.strip(" .") for part in parts if part.strip(" ."))


def parallel_title(record) -> str | None:
    """A second title printed on the publication itself. In the printed volumes ``title_translated`` is the
    editors' translation (square brackets), so only the State Archives' parallel titles count."""
    return record.title_translated if record.source == "vsmart" else None


def strong(reading: Reading) -> bool:
    least = SEGMENT_LATIN if reading.language == "la" else SEGMENT_CONFIDENCE
    return reading.sure and not reading.against and reading.words >= SEGMENT_WORDS and reading.confidence >= least


def suggest(records, identifier: Identifier | None = None) -> dict[str, int]:
    """Set ``language_suggested`` (and the flags ``language-bilingual``, ``language-from-journal`` and
    ``language-from-volume``) on every entry; return counts per language and per route."""
    identifier = identifier or Identifier()
    entries = [record for record in records if record.title and record.role == "entry" and not record.is_cross_listing]
    for record in records:
        record.language_suggested = []
        record.provenance.flags = [flag for flag in record.provenance.flags if not flag.startswith("language-")]

    mains = [main_title(record) for record in entries]
    main_readings = identifier.read(mains)

    # Every part of a title that could be in another language, read on its own, and every parallel title. Quoted
    # words go first: a quoted source title ("'Tout-à-la-fois cultivateurs et commerçans'. Smallholders and …") is
    # not a second language of the publication.
    pieces: list[tuple[int, str]] = []
    for index, (record, text) in enumerate(zip(entries, mains)):
        parts = segments(_QUOTED.sub(" ", text))
        if len(parts) > 1:
            pieces.extend((index, part) for part in parts)
        if parallel := parallel_title(record):
            pieces.append((index, parallel))
    piece_readings = identifier.read([text for _, text in pieces])
    by_entry: dict[int, list[tuple[str, Reading]]] = defaultdict(list)
    for (index, text), reading in zip(pieces, piece_readings):
        by_entry[index].append((text, reading))

    counts: Counter[str] = Counter()
    container_votes: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for index, (record, text, reading) in enumerate(zip(entries, mains, main_readings)):
        if not reading.sure:
            continue
        languages = [code for code in languages_of(record, text, reading.language, by_entry.get(index, []))
                     if code not in NOT_ASSIGNED]
        if not languages:
            continue
        if len(languages) > 1:
            record.provenance.flags.append("language-bilingual")
            counts["bilingual"] += 1
        elif key := container(record):
            container_votes[key][reading.language] += 1
        record.language_suggested = languages
        counts["from title"] += 1

    # A title of names and dates only: the language of its journal, or of the other chapters of its volume.
    lent = {}
    for key, tally in container_votes.items():
        language, top = tally.most_common(1)[0]
        total = sum(tally.values())
        if key[0] == "journal" and total >= JOURNAL_ENTRIES and top >= JOURNAL_SHARE * total:
            lent[key] = language
        elif key[0] == "volume" and total >= VOLUME_ENTRIES and top == total:
            lent[key] = language
    for record in entries:
        key = container(record)
        if not record.language_suggested and key in lent:
            record.language_suggested = [lent[key]]
            record.provenance.flags.append(f"language-from-{key[0]}")
            counts[f"from {key[0]}"] += 1
    for record in entries:
        if record.language_suggested:
            counts.update(f"lang:{code}" for code in record.language_suggested)
        else:
            counts["none"] += 1
    return dict(counts)


def container(record) -> tuple[str, str] | None:
    """The journal of an article (its id, or else its host title as printed) or the volume of a chapter."""
    host = record.host
    if record.type == "article" and (record.journal_id or (host and host.title)):
        return ("journal", record.journal_id or _fold(host.title))
    if record.type == "chapter" and host and (host.id or host.title):
        return ("volume", host.id or f"{record.bgb_year}|{_fold(host.title)}")
    return None


def _fold(text: str) -> str:
    return " ".join(word.lower() for word in _WORD.findall(text))


def languages_of(record, text: str, first: str, pieces: list[tuple[str, Reading]]) -> list[str]:
    """The title's language, and the others of a bilingual title: a parallel title read strongly in another
    language, or parts of the title read strongly in two or more languages that each hold a fair share of it, in
    the order the title gives them. A quotation used as a title ("There's something rotten in the state of Belgium.
    De liquidatie van de repressie …") is too short a share to make the publication bilingual. When the parts
    cover nearly all of the title, they outvote the reading of the whole; otherwise that reading comes last."""
    parallel = parallel_title(record)
    total = letters(text) or 1
    share: Counter[str] = Counter()
    position: dict[str, int] = {}
    second = None
    for order, (piece, reading) in enumerate(pieces):
        if not strong(reading):
            continue
        if piece == parallel:
            if reading.language != first and second is None:
                second = reading.language
            continue
        share[reading.language] += letters(piece)
        position.setdefault(reading.language, order)
    largest = max(share.values(), default=0)
    found = [language for language, size in share.items()
             if size >= SEGMENT_SHARE * total and size >= SEGMENT_RATIO * largest]
    if len(found) > 1 or (found and found[0] != first):
        languages = sorted(found, key=position.__getitem__)
        if first not in languages and sum(share.values()) < SEGMENT_COVER * total:
            languages.append(first)
    else:
        languages = [first]
    if second and second not in languages:
        languages.append(second)
    return languages


SAMPLE_COLUMNS = ["id", "period", "title", "parallel_title", "host", "checked", "note"]


def sample_rows(records, per_period: int = 40, seed: int = 7) -> list[dict[str, str]]:
    """A stratified sample per decade of the BGB volume, to label by hand without seeing the suggestions."""
    import random

    by_period: dict[str, list] = defaultdict(list)
    for record in records:
        if record.title and record.role == "entry" and not record.is_cross_listing and record.bgb_year:
            by_period[f"{record.bgb_year // 10 * 10}s"].append(record)
    rows = []
    rng = random.Random(seed)
    for period in sorted(by_period):
        for record in rng.sample(by_period[period], min(per_period, len(by_period[period]))):
            rows.append({"id": record.id, "period": period, "title": main_title(record),
                         "parallel_title": record.title_translated or "",
                         "host": (record.host.title if record.host else "") or "", "checked": "", "note": ""})
    return rows


def score_rows(records, rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    """Per period and overall: the share of checked entries that got a language (coverage), and the share of those
    whose languages are exactly the checked ones (precision) or start with the right one. ``checked`` holds codes
    separated by "|", or "?" when nothing tells; such rows count for coverage only."""
    by_id = {record.id: record for record in records}
    tally: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        record = by_id.get(row["id"])
        if record is None or not row.get("checked"):
            continue
        truth = [code for code in row["checked"].split("|") if code and code != "?"]
        for key in (row["period"], "all"):
            counts = tally[key]
            counts["checked"] += 1
            if record.language_suggested:
                counts["suggested"] += 1
                if not truth:
                    counts["unknowable"] += 1
                elif record.language_suggested == truth:
                    counts["exact"] += 1
                elif record.language_suggested[0] == truth[0]:
                    counts["first right"] += 1
            elif truth:
                counts["missed"] += 1
    result = {}
    for key, counts in sorted(tally.items()):
        judged = max(1, counts["suggested"] - counts["unknowable"])
        result[key] = {"checked": counts["checked"], "coverage": counts["suggested"] / counts["checked"],
                       "precision": counts["exact"] / judged,
                       "first language right": (counts["exact"] + counts["first right"]) / judged,
                       "missed": counts["missed"]}
    return result
