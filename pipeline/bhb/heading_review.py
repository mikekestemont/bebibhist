"""Codes of the classification proposed for the printed headings of 1952–1992, for a person to review (plan §4i).

The volumes up to 1992 print their own headings ("Betalingsmiddelen, banken en verzekeringsmaatschappijen"), worded
anew from volume to volume; from 1993 on the volumes and the State Archives' records use the classification of
``data/curated/scheme.csv``. A heading is mapped once, not each entry under it: about 2,000 headings hold some 77,000
entries. Two models propose:

- the local classifier of ``bhb categorise`` (titles → code), whose predictions for all the entries under a heading,
  limited to the codes of the heading's period, are averaged: the share of each code;
- a language model that reads the heading itself, its place in the printed table of contents and a few titles, and
  picks one of the codes offered, or answers that the heading is too broad for one code (``BROAD``) or that none fits
  (``NONE``): by default Mistral Small through OpenRouter, the model of the citation pass, with the same pinned
  version, EU routing and cache (Mike, 9 Nov 2026: the local Mistral Small 3.2 took about two minutes for eight
  headings); ``--local`` keeps it on this machine (``bhb.topicmap.Namer``, mlx-lm).

Headings that differ only in numbering, footnote marks, articles or plural endings are one group, asked once. The
proposals go to ``build/headings/`` (a CSV and a spreadsheet to review, largest groups first), not into
``data/curated/heading_crosswalk.csv``: a reviewed answer is copied there afterwards, so nothing reaches the site
unreviewed.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from bhb.model import Record
from bhb.textutil import fold

OLD_ERAS = ("1952-1961", "1962-1992")
# The classifier's codes offered to the model, with the sub-codes of the first few and the upper levels (to three
# levels deep) of the parts the first two belong to; titles shown per heading.
CANDIDATES = 8
WITH_CHILDREN = 4
WITH_UPPER = 2
MAX_OPTIONS = 32
EXAMPLES = 8
# The model of the citation pass (bhb/cli.py, ``citations run``), its version pinned in its id.
MODEL = "mistralai/mistral-small-2603"
SYSTEM = ("You map the headings of the printed Bibliography of Belgian History to the classification it has used "
          "since 1993. Answer with the JSON asked for.")
_STOP = set("le la les l d de des du et en a au aux un une dans sur par pour ou".split())


@dataclass
class Group:
    """Headings that differ only in spelling, with the entries under them."""

    key: str
    rows: list[dict] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    votes: list[tuple[str, float]] = field(default_factory=list)

    @property
    def n(self) -> int:
        return sum(int(row.get("n_entries") or 0) for row in self.rows)

    @property
    def main(self) -> dict:
        return max(self.rows, key=lambda row: int(row.get("n_entries") or 0))

    @property
    def years(self) -> list[int]:
        return sorted({int(year) for row in self.rows for year in (row.get("years") or "").split() if year.isdigit()})


def group_key(example_fr: str) -> str:
    """A heading path compared loosely: without numbering, footnote marks, articles and plural endings."""
    parts = []
    for part in (example_fr or "").split(" / "):
        # Numbering and footnote marks first: folding drops the punctuation that tells them apart.
        part = re.sub(r"\(\s*\d+\s*\)|\(\s*[¹²³⁴⁵⁶⁷⁸⁹⁰]+\s*\)|[¹²³⁴⁵⁶⁷⁸⁹⁰]", "", part)
        part = re.sub(r"^\s*\(?(?:[IVXLCivxlc]+|\d+|[A-Za-z])\s*[.)]\s*", "", part)
        part = fold(part)
        words = [word.rstrip("sx") if len(word) > 3 else word for word in re.findall(r"[a-z0-9]+", part) if word not in _STOP]
        parts.append(" ".join(words))
    return " / ".join(parts)


def groups_of(rows: list[dict]) -> dict[str, Group]:
    """The old headings not yet reviewed, grouped by ``group_key``."""
    found: dict[str, Group] = {}
    for row in rows:
        if row.get("era") not in OLD_ERAS or (row.get("approved_code") or row.get("approved_theme") or "").strip():
            continue
        key = group_key(row.get("example_fr") or row.get("heading_key") or "")
        found.setdefault(key, Group(key)).rows.append(row)
    return found


def collect(records: list[Record], groups: dict[str, Group], rows: list[dict], theme_map) -> None:
    """Each group's titles, and the classifier's average shares over its entries (limited to the period's codes)."""
    import numpy as np

    from bhb.categorise import _fit, _masked, _masks, _predict, _print_entry, document_text, heading_key
    from bhb.facets import periods_from_path

    of_key = {row["heading_key"]: group for group in groups.values() for row in group.rows}
    targets: list[tuple[Group, Record]] = []
    for record in records:
        if _print_entry(record) and record.section_path and (group := of_key.get(heading_key(record.section_path))):
            targets.append((group, record))
            if record.title:
                group.titles.append(record.title)
    by_key = {row["heading_key"]: row for row in rows}
    model, classes, _heldout, _n = _fit(records, rows, by_key, theme_map)
    if model is None:
        raise SystemExit("no classifier: the crosswalk has no reviewed headings to learn from")
    raw = _predict(model, [document_text(record) for _group, record in targets])
    masks = _masks(classes)
    sums: dict[str, np.ndarray] = {}
    counts: dict[str, int] = defaultdict(int)
    for (group, record), vector in zip(targets, raw):
        masked = _masked(vector, masks, periods_from_path(record.section_path))
        if masked is None:
            continue
        sums[group.key] = sums[group.key] + masked if group.key in sums else masked.copy()
        counts[group.key] += 1
    aliases = load_aliases()
    for key, total in sums.items():
        mean = total / counts[key]
        # Shares by current code: a code some volumes numbered otherwise counts as the current one.
        shares: dict[str, float] = defaultdict(float)
        for index in np.argsort(mean)[::-1]:
            if mean[int(index)] > 0:
                shares[aliases.get(classes[int(index)], classes[int(index)])] += float(mean[int(index)])
        groups[key].votes = sorted(shares.items(), key=lambda item: -item[1])[:CANDIDATES]


def load_aliases() -> dict[str, str]:
    """Codes that some printed volumes of 1993–2008 numbered otherwise → the current code (scheme_aliases.csv)."""
    from bhb.paths import repo_root

    with (repo_root() / "data" / "curated" / "scheme_aliases.csv").open(encoding="utf-8", newline="") as handle:
        return {row["code"]: row["current_code"] for row in csv.DictReader(handle) if row.get("code") and row.get("current_code")}


def options(group: Group, scheme: dict) -> list[tuple[str, float | None]]:
    """The codes offered for a group, all of the current classification: the classifier's candidates, the sub-codes
    of the first few, and the upper levels of the parts the first two belong to (so a heading as wide as "Travaux
    généraux / À l'échelon national" can be given its level, II.A.)."""
    current = {code for code, entry in scheme.items() if entry.source == "vsmart"}
    found: dict[str, float | None] = {code: share for code, share in group.votes if code in current}
    for code, _share in group.votes[:WITH_CHILDREN]:
        for child, entry in scheme.items():
            if entry.parent == code and child in current and child not in found:
                found[child] = None
    for code, _share in group.votes[:WITH_UPPER]:
        root = code.split(".")[0] + "."
        for other in scheme:
            if other in current and other.startswith(root) and other.count(".") <= 3 and other not in found:
                found[other] = None
    return list(found.items())[:MAX_OPTIONS]


def prompt(group: Group, offered: list[tuple[str, float | None]], scheme: dict) -> str:
    main = group.main
    years = group.years
    span = f"{years[0]}–{years[-1]}" if len(years) > 1 else (str(years[0]) if years else "?")
    titles = "\n".join(f"- {title[:160]}" for title in _spread(group.titles, EXAMPLES))
    lines = []
    for code, share in offered:
        entry = scheme[code]
        label = entry.label_fr or entry.label_nl or level_name(code, scheme)
        lines.append(f"{code} — {label}" + (f" ({share:.0%} of these publications, by a classifier)" if share else ""))
    return f"""You map a heading of the printed Bibliography of Belgian History (volumes {span}) to the classification the Bibliography has used since 1993.

The heading, in French and in Dutch, after the headings above it:
{main.get("example_fr") or "?"}
{main.get("example_nl") or ""}

{group.n} publications stand under it, for example:
{titles}

The codes you may choose from (code — French label, the levels above it first):
{chr(10).join(lines)}

Choose the code whose subject is the heading's own subject: the same subject, or the closest code that covers the heading as a part (a heading on banks fits a code on finance). The heading's position above (its period, its region) counts as much as its wording. Answer BROAD when the heading spans several of these codes, so that its publications must be classified one by one (general works, a whole period or region without a theme), and NONE when no code fits.

Answer with one line of JSON and nothing else: {{"code": "<a code from the list, BROAD or NONE>", "fit": "<same, part or wider>"}}. "same": heading and code have the same subject; "part": the heading is a part of the code's subject; "wider": the heading covers more than the code."""


def level_name(code: str, scheme: dict) -> str:
    """A level without a label of its own, named from the label of a code below it (whose path names every level)."""
    depth = code.rstrip(".").count(".") + 1
    for other, entry in scheme.items():
        label = entry.label_fr or ""
        if other.startswith(code) and other != code and label.count(" / ") + 1 == other.rstrip(".").count(".") + 1:
            return " / ".join(label.split(" / ")[:depth])
    return ""


def parse(answer: str, offered: list[tuple[str, float | None]]) -> tuple[str, str]:
    """The code and fit of an answer; ("", "") when it cannot be read or names a code not offered."""
    match = re.search(r"\{.*?\}", answer or "", re.S)
    try:
        value = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        return "", ""
    code = str(value.get("code") or "").strip()
    fit = str(value.get("fit") or "").strip().lower()
    allowed = {item for item, _share in offered} | {"BROAD", "NONE"}
    if code not in allowed and code.rstrip(".") + "." in allowed:
        code = code.rstrip(".") + "."
    return (code, fit if fit in ("same", "part", "wider") else "") if code in allowed else ("", "")


def agreement(code: str, votes: list[tuple[str, float]]) -> str:
    """How the model's code stands to the classifier's first candidate."""
    if not code or code in ("BROAD", "NONE") or not votes:
        return ""
    first = votes[0][0]
    if code == first:
        return "agree"
    if code.startswith(first) or first.startswith(code):
        return "related"
    return "differ"


def _spread(items: list[str], n: int) -> list[str]:
    """Up to ``n`` distinct items, spread over the list (the same each run)."""
    distinct = list(dict.fromkeys(item.strip() for item in items if item and item.strip()))
    if len(distinct) <= n:
        return distinct
    step = len(distinct) / n
    return [distinct[int(index * step)] for index in range(n)]


def ask_openrouter(prompts: list[str], offered: list[list[tuple[str, float | None]]], cache: Path, model: str = MODEL,
                   workers: int = 6, log=print) -> list[str]:
    """The answers through OpenRouter, each request cached (``bhb.citations.call``); the answer's code is limited by
    the schema to the codes offered, BROAD and NONE. Returns each answer as JSON text, "" when a request failed."""
    from concurrent.futures import ThreadPoolExecutor

    from bhb.citations import call, request_body

    def ask(index: int):
        codes = [code for code, _share in offered[index]] + ["BROAD", "NONE"]
        schema = {"type": "object", "additionalProperties": False, "required": ["code", "fit"],
                  "properties": {"code": {"type": "string", "enum": codes},
                                 "fit": {"type": "string", "enum": ["same", "part", "wider"]}}}
        return call(request_body(SYSTEM, prompts[index], schema, model, name="heading"), cache)

    answers = [""] * len(prompts)
    cost = 0.0
    with ThreadPoolExecutor(workers) as pool:
        for done, (index, reply) in enumerate(zip(range(len(prompts)), pool.map(ask, range(len(prompts)))), start=1):
            cost += reply.cost
            if reply.content is not None:
                answers[index] = json.dumps(reply.content)
            elif reply.error:
                log(f"headings: request {index + 1} failed: {reply.error}")
            if done % 100 == 0 or done == len(prompts):
                log(f"headings: {done} of {len(prompts)} answered, ${cost:.2f} so far")
    return answers


def propose(records: list[Record], out: Path, limit: int | None = None, local: bool = False, log=print) -> list[dict]:
    """Proposals for every group of unreviewed old headings: ``out/proposals.csv`` and ``out/proposals.xlsx``."""
    from bhb.categorise import crosswalk_path, read_crosswalk
    from bhb.scheme import load_scheme, load_theme_map
    from bhb.topicmap import Namer

    out.mkdir(parents=True, exist_ok=True)
    rows = read_crosswalk(crosswalk_path())
    scheme = load_scheme()
    groups = groups_of(rows)
    log(f"headings: {sum(len(group.rows) for group in groups.values())} unreviewed old headings in {len(groups)} groups")
    collect(records, groups, rows, load_theme_map())
    ordered = sorted(groups.values(), key=lambda group: -group.n)[:limit]
    offered = [options(group, scheme) for group in ordered]
    prompts = [prompt(group, items, scheme) for group, items in zip(ordered, offered)]
    if local:
        namer = Namer(out / "answers-cache.jsonl", log=log)
        answers: list[str] = []
        for start in range(0, len(prompts), 48):
            answers += namer.ask_many(prompts[start : start + 48], max_tokens=40)
            log(f"headings: {min(start + 48, len(prompts))} of {len(prompts)} groups answered")
    else:
        from bhb.paths import build_dir

        answers = ask_openrouter(prompts, offered, build_dir() / "cache" / "headings", log=log)
    result = []
    for rank, (group, items, answer) in enumerate(zip(ordered, offered, answers), start=1):
        code, fit = parse(answer, items)
        votes = group.votes
        share = dict(votes).get(code)
        main = group.main
        result.append({
            "rank": rank,
            "n_entries": group.n,
            "years": " ".join(str(year) for year in group.years),
            "heading_fr": main.get("example_fr", ""),
            "heading_nl": main.get("example_nl", ""),
            "variants": len(group.rows),
            "heading_keys": " ".join(row["heading_key"] for row in group.rows),
            "examples": " | ".join(_spread(group.titles, 5)),
            "proposed_code": code,
            "proposed_label_nl": scheme[code].label_nl if code in scheme else "",
            "proposed_label_fr": scheme[code].label_fr if code in scheme else "",
            "fit": fit,
            "classifier_share": f"{share:.2f}" if share is not None else "",
            "classifier_first": votes[0][0] if votes else "",
            "classifier_first_share": f"{votes[0][1]:.2f}" if votes else "",
            "agreement": agreement(code, votes),
            "answer": (answer or "").strip(),
            "model": "local Mistral-Small-3.2-24B (mlx)" if local else MODEL,
        })
    with (out / "proposals.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result[0]))
        writer.writeheader()
        writer.writerows(result)
    log(f"headings: {len(result)} groups → {out / 'proposals.csv'}")
    return result


# The fits a heading may have to its code to be accepted without review: the same subject, or a part of it.
ACCEPTED_FITS = ("same", "part")
# A group needs this many entries: in a sample, the doubtful agreements were nearly all in groups of a few entries,
# where the classifier's shares rest on two or three titles (9 Nov 2026).
MIN_ENTRIES = 10


def accepted(row: dict) -> bool:
    """A proposal taken without review: the model's code and the classifier's first candidate agree (the same code,
    or the model's a finer or coarser code on the same branch), the fit is not "wider", it is a code, and the group
    has at least MIN_ENTRIES entries."""
    return (row.get("agreement") in ("agree", "related") and row.get("fit") in ACCEPTED_FITS
            and row.get("proposed_code") not in ("", "BROAD", "NONE") and int(row.get("n_entries") or 0) >= MIN_ENTRIES)


def accept(out: Path, log=print) -> list[dict]:
    """The agreed proposals of ``out/proposals.csv`` → ``data/curated/heading_proposals.csv``, one row per heading
    key, marked as the models' (the site shows them as suggested). The others stay for review."""
    from bhb.categorise import heading_proposals_path

    with (out / "proposals.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    kept = []
    for row in rows:
        if not accepted(row):
            continue
        share = row.get("classifier_share") or row.get("classifier_first_share") or ""
        for key in (row.get("heading_keys") or "").split():
            kept.append({
                "heading_key": key,
                "code": row["proposed_code"],
                "confidence": share,
                "agreement": row["agreement"],
                "fit": row["fit"],
                "group_entries": row["n_entries"],
                "heading_fr": row["heading_fr"],
                "proposed_by": f"{row.get('model') or MODEL} + classifier",
            })
    path = heading_proposals_path()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["heading_key", "code", "confidence", "agreement", "fit",
                                                    "group_entries", "heading_fr", "proposed_by"])
        writer.writeheader()
        writer.writerows(kept)
    groups = [row for row in rows if accepted(row)]
    entries = sum(int(row["n_entries"]) for row in groups)
    log(f"headings: {len(groups)} of {len(rows)} groups accepted ({entries} entries), {len(kept)} heading keys → {path}")
    return kept
