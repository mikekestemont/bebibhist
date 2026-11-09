"""A check of the title translations of the citation pass, and their repair (plan §4h).

The pass translated titles 25 to a request (``bhb.citations.ask_titles``), and within a request the model sometimes
gave an entry the translation of a neighbour: four articles of 1979 on the Vatican had as Dutch "translation" the title
of the entry before them, so a search for "Deploige" found them. The ids came back right, so the pass could not tell.

Here a model judges, for every title, whether each of its translations renders that title (``ok``) or not
(``wrong``). Each item carries its own title next to its own translations, so a judgement does not lean on a neighbour
the way a translation did; still, a request whose ids come back wrong is asked again title by title. A translation
judged wrong is made again for that title alone (``ask_titles`` with one item, so there is no neighbour to copy from)
and kept only when the same check judges it ``ok``; otherwise that language is left empty. Every request is cached
(``bhb.citations.call``), so a run resumes, and a later pass that meets the same translations gets the same verdicts.
"""

from __future__ import annotations

import csv
import json
import shutil
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from bhb.citations import Item, ask_titles, call, request_body

MODEL = "mistralai/mistral-small-2603"
BATCH = 10
LANGUAGES = ("nl", "fr", "en")

CHECK = """You check machine translations of titles of publications on Belgian history (the Bibliography of Belgian \
History), made so that readers can find a title by searching in Dutch, French or English.

For each id you get the title as printed and its translations into Dutch (nl), French (fr) and English (en); a \
language is missing where the title is already in it. For each translation given, answer:
- "ok" when it renders this title: free wording, normalised spelling, a place name in that language (Gand/Gent), \
centuries or numbers written otherwise, and a part left out or added in brackets are all fine;
- "wrong" when it renders another title, or changes what the title is about: other persons, places, dates or \
subject, or a large part missing.
Answer "none" for a language without a translation. Judge each id on its own title only."""


def _schema(ids: list[str]) -> dict:
    verdict = {"type": "string", "enum": ["ok", "wrong", "none"]}
    item = {"type": "object", "additionalProperties": False, "required": ["id", *LANGUAGES],
            "properties": {"id": {"type": "string", "enum": ids}, **{code: verdict for code in LANGUAGES}}}
    return {"type": "object", "additionalProperties": False, "required": ["items"],
            "properties": {"items": {"type": "array", "items": item}}}


@dataclass
class Entry:
    id: str
    title: str
    hints: list[str]
    translations: dict[str, str]


def _message(entries: list[Entry]) -> str:
    lines = []
    for entry in entries:
        lines.append(f"[{entry.id}] {entry.title}")
        for code in LANGUAGES:
            lines.append(f"    {code}: {entry.translations.get(code) or '—'}")
    return "\n".join(lines)


def check(entries: list[Entry], cache: Path, model: str = MODEL) -> tuple[dict[str, dict[str, str]], list]:
    """Verdicts per id and language for a batch; asked again title by title when the ids come back wrong."""
    ids = [entry.id for entry in entries]
    reply = call(request_body(CHECK, _message(entries), _schema(ids), model, name="check"), cache)
    items = (reply.content or {}).get("items") or []
    if [item.get("id") for item in items] == ids:
        return {item["id"]: {code: item[code] for code in LANGUAGES} for item in items}, [reply]
    if len(entries) == 1:
        return {}, [reply]
    verdicts, replies = {}, [reply]
    for entry in entries:
        single, more = check([entry], cache, model)
        verdicts.update(single)
        replies.extend(more)
    return verdicts, replies


def repair(entry: Entry, wrong: list[str], cache: Path, model: str = MODEL) -> tuple[dict[str, str | None], list]:
    """New translations for the languages judged wrong, the title alone in its request; a new one is kept only when
    the check judges it ok, else that language is left empty."""
    found, reply = ask_titles([Item(entry.id, entry.title, entry.hints)], model, cache)
    replies = [reply]
    fresh = {code: (found.get(entry.id) or {}).get(code) for code in wrong}
    candidate = Entry(entry.id, entry.title, entry.hints, {**entry.translations, **{code: value for code, value in fresh.items() if value}})
    verdicts, more = check([candidate], cache, model)
    replies.extend(more)
    verdict = verdicts.get(entry.id, {})
    return {code: fresh[code] if fresh.get(code) and verdict.get(code) == "ok" else None for code in wrong}, replies


def run(run_dir: Path, records_path: Path, cache: Path, workers: int = 8, limit: int | None = None,
        only: set[str] | None = None, log=print) -> Counter:
    """Check every translation of ``run_dir/translations.jsonl`` and repair the wrong ones in place (the old file is
    kept as ``translations.before-check.jsonl``); ``run_dir/translation-check.csv`` lists every change."""
    from bhb.io_utils import read_jsonl

    records = {record.id: record for record in read_jsonl(records_path)}
    path = run_dir / "translations.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries = []
    for row in rows:
        record = records.get(row["id"])
        if record is None or (only and row["id"] not in only):
            continue
        given = {code: (row.get(code) or "").strip() for code in LANGUAGES if (row.get(code) or "").strip()}
        title = ": ".join(part for part in (record.title, record.subtitle) if part)
        if record.title_translated:
            title += f" [{record.title_translated}]"
        if given and title:
            entries.append(Entry(row["id"], title, list(record.language_suggested or []), given))
    entries = entries[:limit] if limit else entries
    batches = [entries[start:start + BATCH] for start in range(0, len(entries), BATCH)]
    log(f"translations: {len(entries):,} titles to check in {len(batches):,} requests")
    counts: Counter = Counter()
    lock = threading.Lock()
    verdicts: dict[str, dict[str, str]] = {}

    def tally(replies):
        with lock:
            counts["cost"] += sum(reply.cost for reply in replies)
            counts["requests"] += sum(1 for reply in replies if not reply.cached)
            counts["failed requests"] += sum(1 for reply in replies if reply.content is None)

    with ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(check, batch, cache) for batch in batches]
        for done, future in enumerate(as_completed(futures), start=1):
            found, replies = future.result()
            verdicts.update(found)
            tally(replies)
            if done % 500 == 0 or done == len(futures):
                log(f"translations: {done:,} of {len(futures):,} checked, ${counts['cost']:.2f}")
    by_id = {entry.id: entry for entry in entries}
    to_repair = [(by_id[key], [code for code, verdict in verdict.items() if verdict == "wrong" and code in by_id[key].translations])
                 for key, verdict in verdicts.items()]
    to_repair = [(entry, wrong) for entry, wrong in to_repair if wrong]
    counts["titles checked"] = len(verdicts)
    counts["titles not checked"] = len(entries) - len(verdicts)
    counts["titles with a wrong translation"] = len(to_repair)
    counts["wrong translations"] = sum(len(wrong) for _entry, wrong in to_repair)
    log(f"translations: {len(to_repair):,} titles with a wrong translation; translating them again one by one")
    changes = []
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(repair, entry, wrong, cache): (entry, wrong) for entry, wrong in to_repair}
        for future in as_completed(futures):
            entry, wrong = futures[future]
            fresh, replies = future.result()
            tally(replies)
            for code in wrong:
                counts["repaired" if fresh.get(code) else "left empty"] += 1
                changes.append([entry.id, code, entry.title, entry.translations[code], fresh.get(code) or ""])
    fixed = {}
    for key, code, _title, _old, new in changes:
        fixed.setdefault(key, {})[code] = new or None
    if not limit and not only:
        shutil.copyfile(path, run_dir / "translations.before-check.jsonl")
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                for code, value in fixed.get(row["id"], {}).items():
                    row[code] = value
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (run_dir / "translation-check.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "language", "title", "translation judged wrong", "new translation (empty: left out)"])
        writer.writerows(sorted(changes))
    log(f"translations: {dict(counts)}")
    return counts
