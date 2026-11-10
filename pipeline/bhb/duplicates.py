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
same title stay apart. Entries of one volume printed under two headings stay apart too: that is the volume's own
classification of them.
"""

from __future__ import annotations

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
    """Set ``duplicate_of`` on every listing but one of the same publication in different volumes."""
    groups: dict[tuple, list] = defaultdict(list)
    for record in records:
        record.duplicate_of = None
        key = _key(record)
        if key is not None:
            groups[key].append(record)
    counts: Counter[str] = Counter()
    for key, group in groups.items():
        if len(group) < 2 or len({record.bgb_year for record in group}) < 2:
            continue
        kept = max(group, key=_richness)
        for record in group:
            if record is kept:
                continue
            # Two listings of one volume stay apart; only those of other volumes point to the kept one.
            if record.bgb_year == kept.bgb_year:
                continue
            record.duplicate_of = kept.id
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
