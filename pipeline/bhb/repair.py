"""Damage of the digitisation repaired in the parsed fields, never in the printed text (``bhb citations apply``).

The OCR of the printed volumes split ligatures ("Hansekaufl eute", "Interessenkonfl ikte") and lost the hyphen at a
line break ("Villersen-Brabant", "Haachts oudheiden geschiedkundig tijdschrift"). The citation pass copied these
into the title, the journal and the series (reviewer, 9 Nov 2026). The printed line keeps them; the parsed fields
are repaired where the corpus itself shows the right form, and the record is flagged ``fields-repaired``:

- a split ligature (fl, ffl; fi, ff) is joined when the joined word stands elsewhere in the printed texts. For fi and
  ff the fragment must also be rarer than the joined word, so that "défi de" stays as it is;
- a word with two hyphens or more ("Villers-en-Brabant") that the texts print at least ``MIN_RIGHT`` times replaces
  the same word with one hyphen lost ("Villersen-Brabant"), when that form is at most a third as common;
- a suspended hyphen ("oudheid- en geschiedkundig") replaces the same words with the hyphen and space lost
  ("oudheiden geschiedkundig"), on the same conditions.

A leading dash or stop of a parsed subtitle ("- De eerste voorstellingen …") goes too. One-off misreadings
("Maria-Elisabcth") are hand corrections, ``data/curated/corrections.csv`` (kind ``print``).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

MIN_RIGHT = 3
_WORD = re.compile(r"[^\W\d_]+")
_HYPHENATED = re.compile(r"(?<![\w-])[^\W\d_]+(?:-[^\W\d_]+){2,}(?![\w-])")
_SUSPENDED = re.compile(r"\b([^\W\d_]{3,})- (en|et|und|of|ou|and|or) ([^\W\d_]+)")
_LIGATURE = re.compile(r"\b([^\W\d_]*?(?:ffl|fl|fi|ff))\s([a-zäöüßéèàç][^\W\d_]*)")
_LEAD = re.compile(r"^[\s\-–—.:;,]+")
_TOKEN = re.compile(r"(?<![\w-])[^\W\d_]+(?:-[^\W\d_]+)*")
_CONTINUES = re.compile(r"[\w-]")


@dataclass
class Vocabulary:
    words: Counter = field(default_factory=Counter)
    # Damaged form → right form, for words with hyphens and for suspended hyphens.
    phrases: dict[str, str] = field(default_factory=dict)
    _by_first: dict[str, list[str]] | None = field(default=None, repr=False)

    @classmethod
    def from_texts(cls, texts) -> "Vocabulary":
        words: Counter = Counter()
        hyphenated: Counter = Counter()
        suspended: Counter = Counter()
        texts = list(texts)
        for text in texts:
            words.update(word.lower() for word in _WORD.findall(text))
            hyphenated.update(_HYPHENATED.findall(text))
            suspended.update(_SUSPENDED.findall(text))
        candidates: dict[str, str] = {}
        for form, count in hyphenated.items():
            if count < MIN_RIGHT:
                continue
            parts = form.split("-")
            for at in range(len(parts) - 1):
                damaged = "-".join([*parts[:at], parts[at] + parts[at + 1], *parts[at + 2:]])
                candidates.setdefault(damaged, form)
        for (head, conjunction, tail), count in suspended.items():
            if count >= MIN_RIGHT:
                candidates.setdefault(f"{head}{conjunction} {tail}", f"{head}- {conjunction} {tail}")
        # How often each damaged form is printed, in one pass.
        damaged_counts: Counter = Counter()
        singles = {damaged for damaged in candidates if " " not in damaged}
        pairs = {damaged for damaged in candidates if " " in damaged}
        token = re.compile(r"(?<![\w-])[^\W\d_]+(?:-[^\W\d_]+)*(?![\w-])")
        for text in texts:
            tokens = token.findall(text)
            for item in tokens:
                if item in singles:
                    damaged_counts[item] += 1
            for left, right in zip(tokens, tokens[1:]):
                pair = f"{left} {right}"
                if pair in pairs:
                    damaged_counts[pair] += 1
        right_counts = {**{form: count for form, count in hyphenated.items()},
                        **{f"{h}- {c} {t}": count for (h, c, t), count in suspended.items()}}
        phrases = {
            damaged: right
            for damaged, right in candidates.items()
            if damaged_counts[damaged] and damaged_counts[damaged] * 3 <= right_counts.get(right, 0)
            # The damaged form must not be a word in its own right ("Ronse-Sint-Pieters" vs a real "Ronsesint").
            and not (" " not in damaged and words[damaged.lower()] > damaged_counts[damaged])
        }
        return cls(words=words, phrases=phrases)

    def repair(self, text: str | None) -> str | None:
        if not text:
            return text
        fixed = _LIGATURE.sub(self._join, text)
        if not self.phrases:
            return fixed
        firsts = self._firsts()
        out: list[str] = []
        at = 0
        for match in _TOKEN.finditer(fixed):
            if match.start() < at:
                continue
            word = match.group(0)
            for damaged in firsts.get(word, ()):
                if fixed.startswith(damaged, match.start()) and not _CONTINUES.match(fixed, match.start() + len(damaged)):
                    out.append(fixed[at:match.start()])
                    out.append(self.phrases[damaged])
                    at = match.start() + len(damaged)
                    break
        out.append(fixed[at:])
        return "".join(out)

    def _firsts(self) -> dict[str, list[str]]:
        """The damaged forms by their first word, longest first."""
        if self._by_first is None:
            by_first: dict[str, list[str]] = {}
            for damaged in sorted(self.phrases, key=len, reverse=True):
                by_first.setdefault(damaged.split(" ")[0], []).append(damaged)
            self._by_first = by_first
        return self._by_first

    def _join(self, match: re.Match) -> str:
        left, right = match.group(1), match.group(2)
        joined = (left + right).lower()
        if not self.words[joined]:
            return match.group(0)
        if not left.lower().endswith("fl") and self.words[left.lower()] > self.words[joined]:
            return match.group(0)
        if not left.lower().endswith("fl") and self.words[joined] < MIN_RIGHT:
            return match.group(0)
        return left + right


def _fields(record):
    """The parsed text fields: (getter, setter) pairs."""
    yield record, "title"
    yield record, "subtitle"
    if record.host:
        yield record.host, "title"
        yield record.host, "subtitle"
        if record.host.publisher:
            yield record.host.publisher, "place"
            yield record.host.publisher, "name"
    if record.series:
        yield record.series, "title"
    if record.publisher:
        yield record.publisher, "place"
        yield record.publisher, "name"


def repair_records(records, vocabulary: Vocabulary | None = None) -> dict[str, int]:
    """Repair the parsed fields of every record; the printed text is not touched."""
    vocabulary = vocabulary or Vocabulary.from_texts(record.printed for record in records if record.printed)
    counts: Counter[str] = Counter({"repair rules": len(vocabulary.phrases)})
    for record in records:
        changed = False
        for owner, name in _fields(record):
            value = getattr(owner, name)
            if not value:
                continue
            fixed = vocabulary.repair(value)
            if name == "subtitle":
                fixed = _LEAD.sub("", fixed or "") or None
            if fixed != value:
                setattr(owner, name, fixed)
                changed = True
                counts[f"{type(owner).__name__.lower()}.{name} repaired"] += 1
        if changed:
            counts["records repaired"] += 1
            if "fields-repaired" not in record.provenance.flags:
                record.provenance.flags.append("fields-repaired")
    return dict(counts)
