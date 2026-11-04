"""One name per journal (`docs/JOURNAL_PROPOSAL.md`, steps J1–J3).

The printed volumes abbreviate a journal in many ways ("Rev. b. de phil. et d'h.", "R.B.P.H."). Without a person,
four rules give most spellings a journal:

1. an ISSN: the spelling's articles were matched to Crossref or the VABB-SHW (``bhb identifiers apply``);
2. a frequent spelling written out in full is a journal of its own;
3. an abbreviation belongs to the one full title whose words its words begin, in order;
4. a full title that is another one plus a place, subtitle or volume ("Biekorf (Brugge)") is that journal.

"Ibid." is first replaced by the journal of the previous entry in the same volume. Every link records the rule that
made it; nothing is reviewed yet, and the printed citation and the journal name as printed stay as they are.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from bhb.textutil import fold

STOP = set("de la le les des du d l et en van der den het voor op te in of the and a an und fur zur zum di del della".split())
# Words that name a kind of periodical, not a journal: alone they never make or anchor one.
GENERIC = {"ibid", "ibid pp", "id", "idem", "handelingen", "bulletin", "annales", "annalen", "revue", "tijdschrift",
           "jaarboek", "mededelingen", "bijdragen", "verslagen", "bull", "hand", "ann", "rev", "meded", "jaarb"}
IBID = {"ibid", "id", "idem"}
# A spelling with at least this many articles and no abbreviation dots is taken as a journal's full title.
FULL_TITLE_MIN = 15


def spelling_key(title: str) -> str:
    """A journal name for comparison: folded, without a trailing volume number."""
    return re.sub(r"\s+\d+$", "", fold(title))


def display_title(title: str) -> str:
    """The journal's name to show: a catalogue's note in square brackets ("[voortgezet als = continué par] …") and
    what follows it is left out; a place in round brackets stays, since it tells namesakes apart."""
    return re.sub(r"\s*\[.*$", "", title).strip(" .,;:") or title


# "Title. Ibid., 235, pp. 39–41." where the parser kept no host: the volume, year and pages printed after "Ibid.".
_IBID_PRINTED = re.compile(
    r"\bIbid\.?[.,]?\s*(?:(?P<volume>(?!(?:18|19|20)\d\d\b)[IVXLC]+|\d{1,4})\s*,\s*)?"
    r"(?:(?P<year>(?:18|19|20)\d\d)\s*,\s*)?pp?\.\s*(?P<pages>\d+(?:\s*[-–]\s*\d+)?)"
)


def _is_ibid(title: str | None) -> bool:
    return bool(title) and fold(title).split()[:1] != [] and fold(title).split()[0] in IBID


def _printed_ibid(record):
    """The host an entry prints as "Ibid., pp. …" when the parser left it in the citation only."""
    from bhb.model import Host

    match = _IBID_PRINTED.search(record.printed or "")
    if not match:
        return None
    return Host(title="Ibid.", volume=match.group("volume"), year=match.group("year"),
                pages=re.sub(r"\s*[-–]\s*", "–", match.group("pages")))


def resolve_ibid(records) -> int:
    """Give an entry whose journal or volume is printed as "Ibid." that of the entry printed just before it in the same
    volume, flagged ``host-from-ibid``: the previous entry's journal or volume, or, when the previous entry is a book,
    that book. A journal's volume, issue and year come along when the entry prints none of its own ("Ibid., pp. 57–68"
    is the same issue). When the previous entry is neither, the entry stays as printed. Resolved entries resolve the
    next one in turn. Returns how many were resolved. Runs on a fresh build (``bhb build``), where "Ibid." is still as
    printed."""
    printed = sorted((record for record in records if record.source.startswith("print") and record.print_number and record.print_number.isdigit()),
                     key=lambda record: (record.bgb_year or 0, int(record.print_number)))
    resolved = 0
    for previous, record in zip([None, *printed], printed):
        host = record.host if record.host and record.host.title else _printed_ibid(record)
        if not (host and _is_ibid(host.title)):
            continue
        if previous is None or previous.bgb_year != record.bgb_year:
            continue
        if previous.host and previous.host.title and not _is_ibid(previous.host.title):
            host.title = previous.host.title
            if not (host.volume or host.issue):
                host.volume, host.issue = previous.host.volume, previous.host.issue
                host.year = host.year or previous.host.year
            if previous.type in ("article", "chapter") and record.type not in ("article", "chapter"):
                record.type = previous.type
        elif previous.type == "book" and previous.title:
            host.title = previous.title
            host.year = host.year or (str(previous.year) if previous.year else None)
            record.type = "chapter"
        else:
            continue
        record.host = host
        if not record.year and host.year and host.year.isdigit():
            record.year = int(host.year)
        record.provenance.flags.append("host-from-ibid")
        resolved += 1
    return resolved


def load_successions(path: Path | None = None) -> list[dict[str, str]]:
    from bhb.paths import repo_root

    path = path or repo_root() / "data" / "curated" / "journal_successions.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _content(words: list[str]) -> list[str]:
    return [word for word in words if word not in STOP]


def is_abbreviation(short: str, full: str) -> bool:
    """Every content word of ``short`` begins a later content word of ``full``, in order, starting with the first,
    and together they use most of ``full`` ("bull du c art et h de gembloux" → "bulletin du cercle … gembloux")."""
    abbreviated, written = _content(short.split()), _content(full.split())
    if len(abbreviated) < 2 or len(abbreviated) > len(written) or not written[0].startswith(abbreviated[0]):
        return False
    position = 0
    for word in abbreviated:
        while position < len(written) and not written[position].startswith(word):
            position += 1
        if position == len(written):
            return False
        position += 1
    return len(abbreviated) >= 0.6 * len(written)


def _slug(title: str) -> str:
    return "t:" + re.sub(r"\s+", "-", spelling_key(title))[:60]


def build(records) -> tuple[list[dict], dict[str, tuple[str, str]]]:
    """The journal list and the spelling map: folded spelling → (journal id, rule)."""
    articles = [record for record in records if record.role == "entry" and record.type == "article" and record.host
                and record.host.title and not record.host.title.startswith("[host")]
    count = Counter(spelling_key(record.host.title) for record in articles)
    shown: dict[str, Counter[str]] = defaultdict(Counter)
    for record in articles:
        shown[spelling_key(record.host.title)][record.host.title] += 1
    # 1. ISSNs, the print and online numbers of one journal joined. The lowest number names the group, so a journal
    # keeps its id (and its page's address) when another of its numbers turns up.
    parent: dict[str, str] = {}

    def root(issn: str) -> str:
        parent.setdefault(issn, issn)
        while parent[issn] != issn:
            parent[issn] = parent[parent[issn]]
            issn = parent[issn]
        return issn

    # Two ISSNs on one article are one journal's print and online numbers, unless both have articles of their own and
    # meet on one article only: a renamed journal gets a new ISSN (Crossref lists the old one too), and a matching
    # fault gives an article another journal's number (one DOI of the Ghent Handelingen also lists the Bruges one).
    alone, together = Counter(), Counter()
    for record in articles:
        if len(record.issn) == 1:
            alone[record.issn[0]] += 1
        for issn in record.issn[1:]:
            together[tuple(sorted((record.issn[0], issn)))] += 1
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for record in articles:
        if record.issn:
            for issn in record.issn[1:]:
                pair = tuple(sorted((record.issn[0], issn)))
                if together[pair] < 2 and alone[pair[0]] and alone[pair[1]]:
                    continue
                first, other = root(record.issn[0]), root(issn)
                parent[max(first, other)] = min(first, other)
            votes[spelling_key(record.host.title)][record.issn[0]] += 1
    mapping: dict[str, tuple[str, str]] = {}
    for spelling, counter in votes.items():
        if spelling in GENERIC:
            continue
        journals = Counter()
        for issn, n in counter.items():
            journals[root(issn)] += n
        best, n = journals.most_common(1)[0]
        if n >= 2 * sum(journals.values()) / 3:
            mapping[spelling] = (f"issn:{best}", "issn")
    # 2. Frequent spellings written out in full.
    for spelling, n in count.items():
        if spelling in mapping or spelling in GENERIC or n < FULL_TITLE_MIN:
            continue
        # Written out when abbreviated forms are fewer than one in ten: an OCR slip ("La. Vie wallonne", once among
        # 482) does not make a journal's name an abbreviation.
        abbreviated = sum(k for form, k in shown[spelling].items() if re.search(r"\b\w{1,6}\.", form))
        if abbreviated * 10 < n:
            mapping[spelling] = (_slug(spelling), "full")
    # 4. A full title that is another plus a place, subtitle or volume joins it.
    full = sorted((s for s, (_, rule) in mapping.items() if rule == "full"), key=len)
    for longer in full:
        for shorter in full:
            if shorter != longer and len(shorter) >= 5 and longer.startswith(shorter + " ") and len(longer.split()) - len(shorter.split()) <= 4:
                mapping[longer] = (mapping[shorter][0], "variant")
                break
    # 3. Abbreviations that fit exactly one journal.
    targets = dict(mapping)
    for spelling in count:
        if spelling in mapping or spelling in GENERIC:
            continue
        journals = {targets[target][0] for target in targets if is_abbreviation(spelling, target)}
        if len(journals) == 1:
            mapping[spelling] = (journals.pop(), "abbreviation")
    # 5. A journal renamed under one ISSN: the spellings of its articles from before the new name go to the
    # predecessor (data/curated/journal_successions.csv; the abbreviation rule reads "Bijdragen voor de geschiedenis
    # der Nederlanden" as an abbreviation of BMGN).
    years: dict[str, list[int]] = defaultdict(list)
    for record in articles:
        if year := record.year or record.bgb_year:
            years[spelling_key(record.host.title)].append(int(year))
    successions = load_successions()
    names = {row["predecessor_id"]: row["predecessor_title"] for row in successions}
    for row in successions:
        for spelling, (journal, _rule) in list(mapping.items()):
            dated = sorted(years.get(spelling, []))
            if journal == row["successor"] and dated and dated[len(dated) // 2] < int(row["renamed_in"]):
                mapping[spelling] = (row["predecessor_id"], "predecessor")
    # The list: per journal its ISSNs, the most frequent full spelling as its title, and its article count.
    members: dict[str, list[str]] = defaultdict(list)
    for spelling, (journal, _) in mapping.items():
        members[journal].append(spelling)
    journals = []
    for journal, spellings in members.items():
        # The title is the most frequent spelling written out in full, among all spellings of the journal.
        forms, full_forms = Counter(), Counter()
        for spelling in spellings:
            forms.update(shown[spelling])
            full_forms.update({form: n for form, n in shown[spelling].items() if not re.search(r"\b\w{1,6}\.", form)})
        forms = full_forms or forms
        issns = sorted({issn for issn in parent if journal.startswith("issn:") and root(issn) == journal[5:]})
        # A predecessor is named as the curated list writes it, not by its most frequent spelling.
        title = names.get(journal) or display_title(forms.most_common(1)[0][0])
        journals.append({"id": journal, "title": title, "issn": "|".join(issns),
                         "spellings": len(spellings), "articles": sum(count[s] for s in spellings)})
    journals.sort(key=lambda row: -row["articles"])
    return journals, mapping


def write(journals: list[dict], mapping: dict[str, tuple[str, str]], count: Counter, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "journals.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, ["id", "title", "issn", "spellings", "articles"])
        writer.writeheader()
        writer.writerows(journals)
    with (folder / "journal_spellings.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["spelling", "journal", "rule", "articles"])
        for spelling, (journal, rule) in sorted(mapping.items(), key=lambda item: -count[item[0]]):
            writer.writerow([spelling, journal, rule, count[spelling]])


def previous_ids(folder: Path) -> dict[str, str]:
    """Spelling → journal id in the list written last (``journal_spellings.csv``), or {} when there is none."""
    path = folder / "journal_spellings.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["spelling"]: row["journal"] for row in csv.DictReader(handle)}


def keep_ids(journals: list[dict], mapping: dict[str, tuple[str, str]], count: Counter, previous: dict[str, str]) -> int:
    """A journal named by a spelling (``t:…``) keeps the id most of its articles had in the previous list, so its
    page keeps its address when another spelling becomes its most frequent; an ISSN id is stable by itself. Returns
    how many ids were kept that would have changed."""
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for spelling, (journal, _rule) in mapping.items():
        if journal.startswith("t:") and previous.get(spelling, "").startswith("t:"):
            votes[journal][previous[spelling]] += count[spelling]
    taken = {row["id"] for row in journals}
    renamed: dict[str, str] = {}
    for journal, counter in sorted(votes.items(), key=lambda item: -sum(item[1].values())):
        old = counter.most_common(1)[0][0]
        if old != journal and old not in taken and old not in renamed.values():
            renamed[journal] = old
    for row in journals:
        row["id"] = renamed.get(row["id"], row["id"])
    for spelling, (journal, rule) in mapping.items():
        if journal in renamed:
            mapping[spelling] = (renamed[journal], rule)
    return len(renamed)


def apply_journals(records, folder: Path) -> dict[str, int]:
    """Resolve "Ibid.", build the journal list and give every article its journal id (``journal_id``)."""
    counts = Counter({"ibid resolved": resolve_ibid(records)})
    journals, mapping = build(records)
    articles = Counter(spelling_key(record.host.title) for record in records
                       if record.role == "entry" and record.type == "article" and record.host and record.host.title)
    counts["ids kept"] = keep_ids(journals, mapping, articles, previous_ids(folder))
    write(journals, mapping, articles, folder)
    for record in records:
        record.journal_id = None
        if record.type == "article" and record.host and record.host.title:
            found = mapping.get(spelling_key(record.host.title))
            if found:
                record.journal_id = found[0]
                counts[f"articles by {found[1]}"] += 1
    counts["journals"] = len(journals)
    counts["spellings"] = len(mapping)
    return dict(counts)
