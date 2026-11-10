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
        kept = max(group, key=_richness)
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
