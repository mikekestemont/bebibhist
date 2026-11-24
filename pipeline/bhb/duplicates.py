"""The same publication listed again in a later volume of the Bibliography (``duplicate_of``).

The volumes sometimes list a publication twice, a year or two apart: Jacquemin, "Les Congolais dans la Belgique
'impériale'", in Bancel, Zoos humains (2002), pp. 253–258, is n° 43255 of BGB 2003 and n° 50765 of BGB 2005, the one
with "Jean-Pierre", the other with "J.-P.", an ISBN and the series (reviewer, 9 Nov 2026). Two records that disagree
looked like two publications. The listings are linked: one is kept in search, and the other points to it
(``duplicate_of``); the site opens the kept one at either id and shows both printed texts. Nothing is deleted and the
printed text of each stays as printed.

Two entries are one publication when they are in different volumes, have the same first author and type, the same
title (folded), the same year of publication, and for a chapter or article the same pages, for an article the same
journal. A reprint in another journal, a new edition of another year, or the yearly report of a society with the
same title stay apart.

Two listings in one volume, printed under two headings, are linked the same way (Guy Vanthemsche, 10 Nov 2026: his
notice on Georges Velter in BGB 2002 showed twice, n° 39080 and 39810). The volume's classification of the other
listing is kept: the kept record takes its subjects, periods and heading as well (``_take_subjects``).
"""

from __future__ import annotations

import dataclasses
import re
from collections import Counter, defaultdict

from rapidfuzz import fuzz

from bhb.textutil import fold

_DIGITS = re.compile(r"\d+")


def _key(record) -> tuple | None:
    if record.role != "entry" or record.is_cross_listing or not record.year or not record.title:
        return None
    authors = [person.family for person in record.persons if person.role == "author" and person.family]
    title = " ".join(re.findall(r"[a-z0-9]+", fold(record.title)))
    if not authors or len(title) < 15:
        return None
    kind = "book" if record.type in ("book", "journal-issue") else record.type
    pages = "-".join(_DIGITS.findall(record.host.pages or "")) if record.host else ""
    if kind in ("chapter", "article") and not pages:
        return None
    journal = ""
    if kind == "article":
        journal = record.journal_id or " ".join(re.findall(r"[a-z0-9]+", fold((record.host.title or "") if record.host else "")))
        if not journal:
            return None
    return (fold(authors[0]), title, kind, pages, int(record.year), journal)


def _richness(record) -> tuple:
    """The listing to keep: more identifiers and parsed parts, then fuller given names, then the later volume
    (which often corrects the earlier one)."""
    filled = sum(bool(value) for value in (record.isbn, record.doi, record.issn, record.series, record.publisher,
                                           record.host and record.host.publisher, record.extent, record.kbr))
    given = sum(len(person.given or "") for person in record.persons)
    return (filled, given, record.bgb_year or 0, record.id)


def link_duplicates(records) -> dict[str, int]:
    """Set ``duplicate_of`` on every listing but one of the same publication, in one volume or in several."""
    groups: dict[tuple, list] = defaultdict(list)
    for record in records:
        record.duplicate_of = None
        key = _key(record)
        if key is not None:
            groups[key].append(record)
    counts: Counter[str] = Counter()
    for key, group in groups.items():
        if len(group) < 2:
            continue
        # A printed entry of 2009–2017 and the catalogue's record of it: the catalogue's is kept, as in
        # ``link_print_to_catalogue``.
        paired = any(_printed_catalogue_year(record) for record in group)
        kept = max(group, key=lambda record: (paired and record.source == "vsmart", _richness(record)))
        for record in group:
            if record is kept:
                continue
            record.duplicate_of = kept.id
            if record.bgb_year == kept.bgb_year:
                # The same volume classified it twice: the kept record carries both classifications.
                _take_subjects(kept, record)
                counts[f"{key[2]}s listed twice in one volume"] += 1
            else:
                counts[f"{key[2]}s listed again"] += 1
        counts["publications listed more than once"] += 1
    linked = link_print_to_catalogue(records)
    if linked:
        counts["printed entries linked to their catalogue record"] = linked
    # A chapter linked (Cfr. n°) to a volume's listing that is not kept points to the kept one, so the volume and
    # its chapters stay together on the site.
    kept_of = {record.id: record.duplicate_of for record in records if record.duplicate_of}
    for record in records:
        if record.host and record.host.id in kept_of:
            record.host.id = kept_of[record.host.id]
            counts["chapters moved to the kept volume"] += 1
    return dict(counts)


def _take_subjects(kept, other) -> None:
    """The other listing's heading, subject codes (never primary), subject areas and periods, added to the kept one."""
    if other.section_path and other.section_path != kept.section_path and other.section_path not in kept.secondary_sections:
        kept.secondary_sections.append(list(other.section_path))
    have = {(category.code, category.theme) for category in kept.categories}
    for category in other.categories:
        if (category.code, category.theme) not in have:
            kept.categories.append(dataclasses.replace(category, primary=False))
            have.add((category.code, category.theme))
    for values, suggested, others, others_suggested in (
        (kept.theme, kept.theme_suggested, other.theme, other.theme_suggested),
        (kept.period, kept.period_suggested, other.period, other.period_suggested),
    ):
        for value in others:
            if value not in values:
                values.append(value)
                if value in others_suggested:
                    suggested.append(value)


PRINTED_CATALOGUE_YEARS = range(2009, 2018)


def _printed_catalogue_year(record) -> bool:
    return record.source == "print-pdf" and record.bgb_year in PRINTED_CATALOGUE_YEARS
TITLE_AGREE = 85
# A printed entry and the catalogue's record may lie a volume year apart; a name may be spelled slightly otherwise.
YEAR_LEEWAY = 1
NAME_AGREE = 80
TITLE_CLOSE = 92


def _words(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", fold(text or "")))


# How the catalogue names nobody: an entry the volume prints without an author has "s.n." or "Redactie" there.
_NOBODY = {"s n", "sn", "s", "redactie", "red", "la redaction", "redaction", "anoniem", "anonyme", "anonymous", "anon"}


def _first_family(record) -> str:
    family = _words(record.persons[0].family) if record.persons else ""
    return "" if family in _NOBODY else family


_NOBODY_FIRST = re.compile(r"^\s*(?:Redactie|Red\.|La rédaction)\.?\s*", re.I)


def _names_nobody(record) -> bool:
    """The record names "s.n." or "Redactie" as its author (rather than nobody at all)."""
    return bool(record.persons) and _words(record.persons[0].family) in _NOBODY


def _contains_name(family: str, other: str) -> bool:
    """One family name is a whole part of the other: "Deveen" of "De Pauw-Deveen", "Sindani" of "Kiangu Sindani",
    "Prochno" of "Prochno-Schinkel" (a compound name written in full in one source only)."""
    ours, theirs = family.split(), other.split()
    shorter, longer = sorted((ours, theirs), key=len)
    return bool(shorter) and len(shorter) < len(longer) and all(word in longer for word in shorter) and len("".join(shorter)) >= 4


def _host_printed(record, other) -> bool:
    """The catalogue record's journal or volume is named in the printed entry (or it names none)."""
    host = _words(other.host.title) if other.host and other.host.title else ""
    return not host or host in _words(record.printed)


def _anonymous_fit(record, other) -> bool:
    """A catalogue record by "s.n." or "Redactie" pairs with a printed entry without author when its journal or
    volume is named in the entry and its title has a word, not only years ("1914-1918", "1917": too many entries
    begin so)."""
    return _host_printed(record, other) and bool(re.search(r"[^\W\d_]{3,}", other.title or ""))


def _years_named(text: str) -> set[str]:
    return set(re.findall(r"\b1[0-9]{3}\b|\b20[0-9]{2}\b", text or ""))


def _may_pair(record, other, title: str) -> bool:
    """Titles that both name years share one ("Groot-Poperinge in 1966" is not "… in 1967", a yearly series; a title
    cut short, "Lovanium (1963", still pairs with "(1963-1969)"), and a short title ("Avant-propos", "Inleiding")
    pairs within the same volume year only."""
    ours, theirs = _years_named(record.title), _years_named(f"{other.title} {other.subtitle or ''}")
    if ours and theirs and not ours & theirs:
        return False
    return other.bgb_year == record.bgb_year or len(title.split()) >= 3


def _given_initial(record) -> str:
    given = record.persons[0].given if record.persons else None
    return _words(given)[:1] if given else ""


def link_print_to_catalogue(records) -> int:
    """Link an entry of a printed volume of 2009–2017 to the State Archives' record of the same publication.

    Those years are both printed (``bhb ingest pdfyears``) and in the catalogue's exports; the export lacks about a
    third of the printed entries. The catalogue's record is kept, since it holds the subject codes and the structured
    fields, and the printed entry points to it; the printed heading joins the kept record's subjects
    (``_take_subjects``). A pair has the same first author (or none) and titles that agree (the catalogue's title and
    subtitle against the printed title, word-set ratio 85 or more), in the same volume year or, once every entry has
    had its chance there, the next or previous one (the catalogue files some publications a year apart). A
    second pass takes a first author spelled slightly otherwise ("Boutrue" and "Boutroue", "Dekoninck" and
    "Deconinck": name ratio 80 or more, the same initial of the given name) when the titles agree closely (ratio 92
    or more). Titles that name years must name the same ones, and a short title pairs within its volume year only
    (``_may_pair``). Each catalogue record takes one printed entry, the closest."""
    catalogue: dict[str, list] = defaultdict(list)
    for record in records:
        if (record.source == "vsmart" and record.role == "entry" and record.title
                and record.bgb_year in range(PRINTED_CATALOGUE_YEARS.start - YEAR_LEEWAY, PRINTED_CATALOGUE_YEARS.stop + YEAR_LEEWAY)
                and not record.duplicate_of):
            catalogue[_first_family(record)].append(record)
    used: set[str] = set()
    linked = 0

    def link(record, best) -> None:
        nonlocal linked
        used.add(best.id)
        record.duplicate_of = best.id
        _take_subjects(best, record)
        linked += 1

    printed = [record for record in records
               if record.source == "print-pdf" and record.bgb_year in PRINTED_CATALOGUE_YEARS and record.role == "entry"
               and not record.is_cross_listing and record.title and not record.duplicate_of]
    # The same volume year first, for every entry, then a year apart: an entry of the next volume does not take the
    # record that the same year's entry pairs with.
    for leeway in (0, YEAR_LEEWAY):
        for record in printed:
            if record.duplicate_of:
                continue
            family = _first_family(record)
            # No author on either side ("s.n." or "Redactie" in the catalogue, read as nobody): the printed title often
            # carries more (a "Redactie." before it, a subtitle, the journal's first words); against a catalogue
            # record that names "s.n." or "Redactie", its journal or volume must be named in the printed entry.
            title = _words(record.title if family else _NOBODY_FIRST.sub("", record.title))
            best, best_score = None, 0.0
            for other in catalogue.get(family, ()):
                if (other.id in used or abs(other.bgb_year - record.bgb_year) != leeway or not _may_pair(record, other, title)
                        or (not family and _names_nobody(other) and not _anonymous_fit(record, other))):
                    continue
                score = fuzz.token_set_ratio(title, _words(f"{other.title} {other.subtitle or ''}"))
                if score >= TITLE_AGREE and score > best_score:
                    best, best_score = other, score
            if best is not None:
                link(record, best)
    # Second pass: a first author spelled slightly otherwise, the titles close.
    by_initial: dict[str, list] = defaultdict(list)
    for family, others in catalogue.items():
        if family:
            by_initial[family[:1]].extend(others)
    for record in printed:
        family = _first_family(record)
        if record.duplicate_of or not family:
            continue
        title, initial = _words(record.title), _given_initial(record)
        best, best_score = None, 0.0
        for other in by_initial.get(family[:1], ()):
            if (other.id in used or abs(other.bgb_year - record.bgb_year) > YEAR_LEEWAY or _given_initial(other) != initial
                    or not _may_pair(record, other, title)):
                continue
            other_family = _first_family(other)
            if other_family == family or (fuzz.ratio(family, other_family) < NAME_AGREE and not _contains_name(family, other_family)):
                continue
            score = fuzz.ratio(title, _words(f"{other.title} {other.subtitle or ''}"))
            score = max(score, fuzz.ratio(title, _words(other.title)))
            if score >= TITLE_CLOSE and score > best_score:
                best, best_score = other, score
        if best is not None:
            link(record, best)
    return linked
