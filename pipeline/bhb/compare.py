"""A new build against the data on the site (``bhb compare``), before it is packed for a release.

Counts the entries per source and volume year and, on the entries both builds hold, what each field gained, lost and
changed. A year that shrank, or a field that lost more than a small share, stops the release chain (exit 2): on 24 Nov
2026 the comparison showed KBR links, journal ids and links between listings that a run had lost, each time through
an order of steps or a rule that no test had caught. The deployed data is the newest ``build/records.deployed-*.jsonl``;
after a deploy, ``build/records.jsonl`` is copied to a new one.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Callable

# A source's volume year may lose this share of its entries, a field this share of its values on the common entries
# (and this many at least), before the comparison stops the chain.
YEAR_SHARE = 0.005
FIELD_SHARE = 0.005
FIELD_MIN = 50

FIELDS: dict[str, Callable[[dict], object]] = {
    "title": lambda r: r.get("title"), "persons": lambda r: r.get("persons"), "year": lambda r: r.get("year"),
    "host": lambda r: (r.get("host") or {}).get("title"), "doi": lambda r: r.get("doi"), "isbn": lambda r: r.get("isbn"),
    "issn": lambda r: r.get("issn"), "kbr": lambda r: r.get("kbr"), "journal_id": lambda r: r.get("journal_id"),
    "duplicate_of": lambda r: r.get("duplicate_of"), "language": lambda r: r.get("language") or r.get("language_suggested"),
    "translations": lambda r: r.get("translations"), "bhb_codes": lambda r: r.get("bhb_codes"), "categories": lambda r: r.get("categories"),
    "places": lambda r: r.get("place_ids"), "topic": lambda r: r.get("topic"), "similar": lambda r: r.get("similar"),
    "parsed by the pass": lambda r: "parsed-llm" in ((r.get("provenance") or {}).get("flags") or []),
}
# Remade by every new map or index of neighbours: only a loss says something, and the share is wider.
_REMADE = {"topic", "similar"}


def load(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as lines:
        return {row["id"]: row for row in map(json.loads, lines)}


def newest_deployed(folder: Path) -> Path | None:
    found = sorted(folder.glob("records.deployed-*.jsonl"))
    return found[-1] if found else None


def compare(old: dict[str, dict], new: dict[str, dict], examples: int = 3) -> tuple[list[str], list[str]]:
    """The report's lines, and the problems that should stop a release."""
    lines, problems = [f"Entries: {len(old):,} → {len(new):,}", ""], []
    years = lambda rows: Counter((row["source"], row.get("bgb_year")) for row in rows.values())
    before, after = years(old), years(new)
    for key in sorted(set(before) | set(after), key=str):
        if before[key] != after[key]:
            lines.append(f"- {key[0]} {key[1]}: {before[key]:,} → {after[key]:,}")
            if before[key] - after[key] > max(2, before[key] * YEAR_SHARE):
                problems.append(f"{key[0]} {key[1]} went from {before[key]:,} to {after[key]:,} entries")
    common = old.keys() & new.keys()
    gone = old.keys() - new.keys()
    lines += ["", f"Entries gone: {len(gone):,}; new: {len(new.keys() - old.keys()):,}; in both: {len(common):,}", "",
              "| Field | On the site | New build | Gained | Lost | Changed |", "|---|---:|---:|---:|---:|---:|"]
    details: list[str] = []
    for name, get in FIELDS.items():
        had = gained = lost = changed = 0
        sample: list[str] = []
        for rid in common:
            a, b = get(old[rid]), get(new[rid])
            had += bool(a)
            if b and not a:
                gained += 1
            elif a and not b:
                # A link between two listings may turn round: the pair is still linked.
                if name == "duplicate_of" and new.get(a, {}).get("duplicate_of") == rid:
                    changed += 1
                    continue
                lost += 1
                if len(sample) < examples:
                    sample.append(f"{rid} ({(new[rid].get('title') or '')[:60]})")
            elif a and b and a != b:
                changed += 1
        lines.append(f"| {name} | {sum(bool(get(row)) for row in old.values()):,} | {sum(bool(get(row)) for row in new.values()):,} | {gained:,} | {lost:,} | {changed:,} |")
        if sample:
            details.append(f"- {name} lost, e.g. {'; '.join(sample)}")
        if lost > max(FIELD_MIN, had * FIELD_SHARE * (3 if name in _REMADE else 1)):
            problems.append(f"{name}: lost on {lost:,} of {had:,} entries")
    return lines + ["", *details], problems


def run(old: Path | None, new: Path | None, folder: Path) -> int:
    old, new = old or newest_deployed(folder), new or folder / "records.jsonl"
    if old is None:
        print("compare: no build/records.deployed-*.jsonl to compare with")
        return 0
    lines, problems = compare(load(old), load(new))
    lines = [f"# {new.name} against {old.name}", "", *lines, "", "## To look at before a release", "", *([f"- {problem}" for problem in problems] or ["- nothing"])]
    (folder / "compare.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"compare: {len(problems)} to look at → {folder / 'compare.md'}")
    return 2 if problems else 0


