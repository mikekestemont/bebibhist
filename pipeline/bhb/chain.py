"""The release chain of pipeline/README.md as one command, so a run is never typed by hand.

    bhb chain --list                       the steps, numbered
    bhb chain --from citations-apply --map --remote-names    from `citations apply` on, with a new topic map
    bhb chain --max-parse 100 --max-translate 20

Each step runs as its own `bhb …` process; the chain stops at the first step that fails, and every step's output is
also written to build/chain.log. Before `citations run`, the only paid step, the chain runs `citations run --dry-run`
and stops when more requests than `--max-parse` and `--max-translate` (default 0: only what the cache holds) would be
sent, so nothing is paid for that was not allowed beforehand. The checks of the new translations, sent by the run
itself, are not counted by the dry run (about one in eight of the translations; plan §4h).
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class Step:
    label: str
    args: tuple[str, ...]
    note: str = ""
    map_only: bool = False  # only with --map: the layout and the region names are made again


# The order of the README's release chain (pipeline/README.md, "A release is made from a full run").
STEPS: tuple[Step, ...] = (
    Step("build", ("build",)),
    Step("journals", ("journals", "apply"), "printed articles need their journal id for their identifiers"),
    Step("identifiers", ("identifiers", "apply"), "the pass leaves out printed entries with a DOI"),
    Step("language", ("language", "apply"), "each request carries the language as a hint (the cache key)"),
    Step("citations-run", ("citations", "run"), "paid: guarded by a dry run"),
    Step("citations-apply", ("citations", "apply")),
    Step("similar", ("similar",), "a build drops the neighbours"),
    Step("facets", ("facets", "apply")),
    Step("places", ("places", "apply")),
    Step("journals-again", ("journals", "apply"), "once before the identifiers: the DOI of a printed article is found by its journal's ISSN"),
    Step("match-crossref", ("identifiers", "match", "--source", "all", "--new", "--patient", "16"), "new entries only; one question a second, hours after a delivery"),
    Step("match-vabb", ("identifiers", "vabb")),
    Step("match-kbr", ("identifiers", "kbr"), "on the citation pass's fields: on the parser's, 440 links were lost (23 Nov 2026)"),
    Step("identifiers-again", ("identifiers", "apply")),
    Step("journals-last", ("journals", "apply"), "Ibid., journal ids, duplicates"),
    Step("language-again", ("language", "apply")),
    Step("topicmap-layout", ("topicmap", "layout"), "about 5 minutes", map_only=True),
    Step("topicmap-names", ("topicmap", "names"), "the local model, about two hours; --remote-names: OpenRouter, minutes", map_only=True),
    Step("topicmap-apply", ("topicmap", "apply")),
    Step("compare", ("compare",), "with the data on the site; stops the chain when something went missing"),
    Step("release", ("release",), "packs the dataset; publishes nothing"),
)

_PARSE = re.compile(r"^dry run: ([\d,]+) parse requests not in the cache", re.M)
_TRANSLATE = re.compile(r"to translate in ([\d,]+) requests", re.M)


def _index(name: str | int | None, default: int) -> int:
    """A step's position (0-based) from its number (1-based) or its label."""
    if name is None:
        return default
    text = str(name)
    if text.isdigit():
        number = int(text)
        if not 1 <= number <= len(STEPS):
            raise SystemExit(f"chain: no step {number} (1–{len(STEPS)})")
        return number - 1
    for position, step in enumerate(STEPS):
        if step.label == text:
            return position
    raise SystemExit(f"chain: no step {text!r}; bhb chain --list names them")


def plan(start: str | int | None = None, stop: str | int | None = None, with_map: bool = False,
         build_flags: Iterable[str] = (), remote_names: bool = False) -> list[tuple[int, Step, list[str]]]:
    """The steps to run, as (number, step, bhb arguments), from ``start`` to ``stop`` included."""
    first, last = _index(start, 0), _index(stop, len(STEPS) - 1)
    if first > last:
        raise SystemExit(f"chain: step {first + 1} comes after step {last + 1}")
    chosen = []
    for position in range(first, last + 1):
        step = STEPS[position]
        if step.map_only and not with_map:
            continue
        args = list(step.args) + (list(build_flags) if step.label == "build" else [])
        if step.label == "topicmap-names" and remote_names:
            args.append("--remote")
        chosen.append((position + 1, step, args))
    return chosen


def dry_run_counts(output: str) -> tuple[int, int] | None:
    """Parse requests and translation requests that `citations run --dry-run` reports as not in the cache."""
    parse = _PARSE.search(output)
    if not parse:
        return None
    translate = _TRANSLATE.search(output)  # every translation request counts, even one the cache may hold
    if not translate:
        return None
    return int(parse.group(1).replace(",", "")), int(translate.group(1).replace(",", ""))


Runner = Callable[[list[str], Path], tuple[int, str]]


def run_bhb(args: list[str], log: Path) -> tuple[int, str]:
    """Run `bhb <args>` in a child process, echo and log its output, and return its exit code and output."""
    process = subprocess.Popen([sys.executable, "-m", "bhb", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
    lines = []
    with log.open("a", encoding="utf-8") as handle:
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            handle.write(line)
            handle.flush()
            lines.append(line)
    return process.wait(), "".join(lines)


def _note(log: Path, text: str) -> None:
    print(text, flush=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def run_chain(steps: list[tuple[int, Step, list[str]]], log: Path, max_parse: int = 0, max_translate: int = 0,
              runner: Runner = run_bhb) -> int:
    """Run the steps in order; 0 when all ran, otherwise the exit code of the step that failed (3 for the guard)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    _note(log, f"\n##### {time.strftime('%Y-%m-%d %H:%M')} bhb chain: steps {', '.join(str(n) for n, _, _ in steps)}")
    for number, step, args in steps:
        if step.label == "citations-run":
            _note(log, f"\n=== {time.strftime('%H:%M')} step {number} guard: bhb {' '.join(args)} --dry-run")
            code, output = runner([*args, "--dry-run"], log)
            counts = dry_run_counts(output) if code == 0 else None
            if counts is None:
                _note(log, f"chain: the dry run gave no counts (exit {code}); stopped before the paid step, nothing sent")
                return code or 3
            parse, translate = counts
            if parse > max_parse or translate > max_translate:
                _note(log, f"chain: STOP before the paid step: {parse:,} parse and {translate:,} translation requests not in "
                           f"the cache (allowed {max_parse:,} and {max_translate:,}); nothing was sent. Rerun with "
                           f"--from {number} --max-parse {parse} --max-translate {translate} once that is agreed.")
                return 3
            _note(log, f"chain: guard passed: {parse:,} parse and {translate:,} translation requests to send "
                       f"(allowed {max_parse:,} and {max_translate:,})")
        _note(log, f"\n=== {time.strftime('%H:%M')} step {number} {step.label}: bhb {' '.join(args)}")
        started = time.time()
        code, _ = runner(args, log)
        if code != 0:
            _note(log, f"chain: step {number} ({step.label}) failed with exit {code}; stopped, later steps not run")
            return code
        _note(log, f"=== step {number} done in {(time.time() - started) / 60:.0f} min")
    _note(log, f"\n##### {time.strftime('%H:%M')} bhb chain: done")
    return 0


def list_steps() -> str:
    lines = []
    for number, step in enumerate(STEPS, 1):
        extra = " [only with --map]" if step.map_only else ""
        note = f"  ({step.note})" if step.note else ""
        lines.append(f"{number:>2}. {step.label:<18} bhb {' '.join(step.args)}{extra}{note}")
    return "\n".join(lines)
