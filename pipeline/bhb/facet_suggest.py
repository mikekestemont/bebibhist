"""Facet values suggested from neighbours in meaning (step F3 of ``docs/FACET_PROPOSAL.md``).

For an entry, take its K closest entries that carry *checked* values (a V-Smart code, or a printed heading whose
number and wording agree), and score each value by the share of their similarity that carries it. Several values
may pass, so an entry can get more than one subject area or period. A value is kept only above a threshold chosen
on held-out years so that at least 90 % of the kept values are right. Nothing here writes to the records.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from bhb.facets import assign_period
from bhb.model import Record
from bhb.scheme import themes_for_code

K = 20
PRECISION = 0.90
FLOOR = 0.60
THRESHOLDS = [round(0.30 + 0.05 * step, 2) for step in range(14)]
# A value needs this many held-out suggestions at a threshold before its precision there is trusted.
MIN_SUGGESTIONS = 50
# "aux" and "general" are parts of the bibliography, not periods.
REAL_PERIODS = ("ancient", "medieval", "burgundian", "early-modern", "contemporary")


def checked_codes(record: Record) -> list[str]:
    return [category.code for category in record.categories if category.code and not category.machine]


def checked_themes(record: Record, theme_map: list[tuple[str, str]]) -> set[str]:
    found: set[str] = set()
    for category in record.categories:
        if category.machine:
            continue
        if category.code:
            found.update(themes_for_code(category.code, theme_map))
        elif category.theme:
            found.add(category.theme)
    return found


def checked_periods(record: Record) -> set[str]:
    return {period for period in assign_period(record.section_path, checked_codes(record)) if period in REAL_PERIODS}


def held_out(record: Record) -> bool:
    """The plan's split by year: V-Smart 2015–2017 and print 2005–2008 are held out."""
    year = record.bgb_year or 0
    return year >= 2015 if record.source == "vsmart" else year >= 2005


def label_scores(similarities: np.ndarray, neighbour_labels: list[set[str]]) -> dict[str, float]:
    """Each value's share of the neighbours' similarity; several values can pass together."""
    weights = np.clip(similarities, 0.0, None)
    total = float(weights.sum())
    if total <= 0:
        return {}
    scores: dict[str, float] = defaultdict(float)
    for weight, labels in zip(weights.tolist(), neighbour_labels):
        for label in labels:
            scores[label] += weight / total
    return dict(scores)


@dataclass
class Evaluation:
    threshold: float
    precision: float
    recall: float
    coverage: float
    predicted: int


def evaluate(scored: list[dict[str, float]], truth: list[set[str]], threshold: float) -> Evaluation:
    predicted = correct = true_total = covered = 0
    for scores, gold in zip(scored, truth):
        chosen = {label for label, score in scores.items() if score >= threshold}
        predicted += len(chosen)
        correct += len(chosen & gold)
        true_total += len(gold)
        covered += bool(chosen)
    return Evaluation(
        threshold=threshold,
        precision=correct / predicted if predicted else 0.0,
        recall=correct / true_total if true_total else 0.0,
        coverage=covered / len(truth) if truth else 0.0,
        predicted=predicted,
    )


def choose_threshold(curve: list[Evaluation], precision: float = PRECISION, floor: float = FLOOR) -> Evaluation | None:
    """The lowest threshold, not below the floor, whose kept values are right at least ``precision`` of the time."""
    passing = [point for point in curve if point.threshold >= floor and point.predicted and point.precision >= precision]
    return min(passing, key=lambda point: point.threshold) if passing else None


def label_thresholds(scored: list[dict[str, float]], truth: list[set[str]], floor: float = FLOOR) -> dict[str, tuple[float, int, float]]:
    """Per value: the lowest threshold (not below the floor) at which at least 90 % of its held-out suggestions
    are right, with the number of suggestions and their precision there. Values that never get there are absent."""
    found: dict[str, tuple[float, int, float]] = {}
    labels = sorted({label for scores in scored for label in scores})
    for label in labels:
        for threshold in THRESHOLDS:
            if threshold < floor:
                continue
            made = [label in gold for scores, gold in zip(scored, truth) if scores.get(label, 0.0) >= threshold]
            if len(made) >= MIN_SUGGESTIONS and sum(made) / len(made) >= PRECISION:
                found[label] = (threshold, len(made), sum(made) / len(made))
                break
    return found


def per_label_precision(scored: list[dict[str, float]], truth: list[set[str]], threshold: float) -> dict[str, tuple[int, float]]:
    made: Counter[str] = Counter()
    hits: Counter[str] = Counter()
    for scores, gold in zip(scored, truth):
        for label, value in scores.items():
            if value >= threshold:
                made[label] += 1
                hits[label] += label in gold
    return {label: (made[label], hits[label] / made[label]) for label in sorted(made)}


@dataclass
class FacetRun:
    name: str
    curve: list[Evaluation]
    chosen: Evaluation | None
    per_label: dict[str, tuple[int, float]] = field(default_factory=dict)
    thresholds: dict[str, tuple[float, int, float]] = field(default_factory=dict)
    suggestions: dict[str, set[str]] = field(default_factory=dict)
    combined: Evaluation | None = None
    headings: dict[str, dict[str, float]] = field(default_factory=dict)


def neighbours_in_pool(queries: np.ndarray, pool: np.ndarray, k: int = K, chunk: int = 2048):
    """Top-k pool rows for every query row, by cosine (the vectors are normalised)."""
    try:
        import torch
    except ImportError:
        torch = None
    if torch is not None:
        device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
        bank = torch.from_numpy(pool).to(device)
        for start in range(0, queries.shape[0], chunk):
            block = torch.from_numpy(queries[start : start + chunk]).to(device)
            values, columns = torch.topk(block @ bank.T, k, dim=1)
            yield start, columns.cpu().numpy(), values.cpu().numpy()
        return
    for start in range(0, queries.shape[0], chunk):
        scores = queries[start : start + chunk] @ pool.T
        columns = np.argsort(-scores, axis=1)[:, :k]
        yield start, columns, np.take_along_axis(scores, columns, axis=1)


def run_facet(
    name: str,
    ids: list[str],
    matrix: np.ndarray,
    labels: dict[str, set[str]],
    is_held_out: dict[str, bool],
    targets: list[str],
    k: int = K,
) -> FacetRun:
    """Train on labelled entries outside the held-out years, measure on the held-out ones, suggest for ``targets``."""
    row = {record_id: index for index, record_id in enumerate(ids)}
    train = [record_id for record_id in ids if labels.get(record_id) and not is_held_out[record_id]]
    test = [record_id for record_id in ids if labels.get(record_id) and is_held_out[record_id]]
    pool = matrix[[row[record_id] for record_id in train]]
    pool_labels = [labels[record_id] for record_id in train]

    def score(query_ids: list[str]) -> list[dict[str, float]]:
        out: list[dict[str, float]] = []
        queries = matrix[[row[record_id] for record_id in query_ids]]
        for _start, columns, values in neighbours_in_pool(queries, pool, k):
            for line in range(columns.shape[0]):
                out.append(label_scores(values[line], [pool_labels[column] for column in columns[line]]))
        return out

    test_scores = score(test)
    truth = [labels[record_id] for record_id in test]
    curve = [evaluate(test_scores, truth, threshold) for threshold in THRESHOLDS]
    chosen = choose_threshold(curve)
    per_label = per_label_precision(test_scores, truth, chosen.threshold if chosen else FLOOR)
    thresholds = label_thresholds(test_scores, truth)

    def pick(scores: dict[str, float]) -> set[str]:
        return {label for label, value in scores.items() if label in thresholds and value >= thresholds[label][0]}

    # The held-out result of the per-value thresholds, all values together.
    predicted = correct = covered = true_total = 0
    for scores, gold in zip(test_scores, truth):
        picked = pick(scores)
        predicted += len(picked)
        correct += len(picked & gold)
        covered += bool(picked)
        true_total += len(gold)
    combined = Evaluation(
        threshold=float("nan"),
        precision=correct / predicted if predicted else 0.0,
        recall=correct / true_total if true_total else 0.0,
        coverage=covered / len(truth) if truth else 0.0,
        predicted=predicted,
    )
    suggestions: dict[str, set[str]] = {}
    if thresholds and targets:
        for record_id, scores in zip(targets, score(targets)):
            picked = pick(scores)
            if picked:
                suggestions[record_id] = picked
    return FacetRun(name, curve, chosen, per_label, thresholds, suggestions, combined)


def sample(records: list[Record], suggestions: dict[str, set[str]], size: int = 20, seed: int = 7) -> list[tuple[Record, set[str]]]:
    by_id = {record.id: record for record in records}
    chosen = random.Random(seed).sample(sorted(suggestions), min(size, len(suggestions)))
    return [(by_id[record_id], suggestions[record_id]) for record_id in chosen]


MIN_GROUP = 5
# A heading's score is an average over its entries, so it is lower than a single entry's; its threshold is still
# chosen so that 90 % of the held-out entries under suggested headings carry the value.
HEADING_FLOOR = 0.30


def pooled(group_ids: list[str], scores: list[dict[str, float]], groups: dict[str, str]) -> dict[str, dict[str, float]]:
    """The mean score of every value over the entries under one printed heading, for headings with enough entries."""
    members: dict[str, list[dict[str, float]]] = defaultdict(list)
    for record_id, entry_scores in zip(group_ids, scores):
        members[groups[record_id]].append(entry_scores)
    means: dict[str, dict[str, float]] = {}
    for key, rows in members.items():
        if len(rows) < MIN_GROUP:
            continue
        total: dict[str, float] = defaultdict(float)
        for entry_scores in rows:
            for label, value in entry_scores.items():
                total[label] += value / len(rows)
        means[key] = dict(total)
    return means


def run_headings(
    name: str,
    ids: list[str],
    matrix: np.ndarray,
    labels: dict[str, set[str]],
    is_held_out: dict[str, bool],
    groups: dict[str, str],
    targets: list[str],
    k: int = K,
    floor: float = HEADING_FLOOR,
) -> FacetRun:
    """As ``run_facet``, but a value is suggested for a whole printed heading: the title scores of all entries under
    it are averaged. Measured on the held-out printed years, grouped the same way, from titles only."""
    row = {record_id: index for index, record_id in enumerate(ids)}
    train = [record_id for record_id in ids if labels.get(record_id) and not is_held_out[record_id]]
    pool = matrix[[row[record_id] for record_id in train]]
    pool_labels = [labels[record_id] for record_id in train]

    def score(query_ids: list[str]) -> list[dict[str, float]]:
        out: list[dict[str, float]] = []
        queries = matrix[[row[record_id] for record_id in query_ids]]
        for _start, columns, values in neighbours_in_pool(queries, pool, k):
            for line in range(columns.shape[0]):
                out.append(label_scores(values[line], [pool_labels[column] for column in columns[line]]))
        return out

    held = [record_id for record_id in ids if is_held_out[record_id] and record_id in groups]
    heading_scores = pooled(held, score(held), groups)
    test = [record_id for record_id in held if labels.get(record_id) and groups[record_id] in heading_scores]
    test_scores = [heading_scores[groups[record_id]] for record_id in test]
    truth = [labels[record_id] for record_id in test]
    curve = [evaluate(test_scores, truth, threshold) for threshold in THRESHOLDS]
    chosen = choose_threshold(curve)
    per_label = per_label_precision(test_scores, truth, chosen.threshold if chosen else floor)
    thresholds = label_thresholds(test_scores, truth, floor)

    def pick(scores: dict[str, float]) -> set[str]:
        return {label for label, value in scores.items() if label in thresholds and value >= thresholds[label][0]}

    predicted = correct = covered = true_total = 0
    for scores, gold in zip(test_scores, truth):
        picked = pick(scores)
        predicted += len(picked)
        correct += len(picked & gold)
        covered += bool(picked)
        true_total += len(gold)
    combined = Evaluation(float("nan"), correct / predicted if predicted else 0.0, correct / true_total if true_total else 0.0, covered / len(truth) if truth else 0.0, predicted)
    suggestions: dict[str, set[str]] = {}
    target_headings: dict[str, dict[str, float]] = {}
    grouped_targets = [record_id for record_id in targets if record_id in groups]
    if thresholds and grouped_targets:
        target_headings = pooled(grouped_targets, score(grouped_targets), groups)
        for record_id in grouped_targets:
            picked = pick(target_headings.get(groups[record_id], {}))
            if picked:
                suggestions[record_id] = picked
    return FacetRun(name, curve, chosen, per_label, thresholds, suggestions, combined, target_headings)


def suggest_command(records_path, build_dir) -> list[str]:
    """Run both experiments and write ``facet_report.md`` and ``heading_subject_proposals.csv``. Returns the paths."""
    import csv
    from pathlib import Path

    from bhb.categorise import heading_key
    from bhb.io_utils import read_jsonl
    from bhb.scheme import load_theme_map
    from bhb.similar import DEFAULT_MODEL, encode

    build = Path(build_dir)
    records = [record for record in read_jsonl(Path(records_path)) if record.role == "entry" and not record.is_cross_listing]
    vectors = encode(records, DEFAULT_MODEL, build / "vectors" / f"{DEFAULT_MODEL.replace('/', '__')}.npz")
    by_id = {record.id: record for record in records}
    theme_map = load_theme_map()
    themes = {record_id: checked_themes(by_id[record_id], theme_map) for record_id in vectors.ids}
    periods = {record_id: checked_periods(by_id[record_id]) for record_id in vectors.ids}
    held = {record_id: held_out(by_id[record_id]) for record_id in vectors.ids}
    # The same heading wording means another heading before and after the 1993 scheme.
    groups = {
        record_id: f"{'old' if (by_id[record_id].bgb_year or 0) < 1993 else 'new'}|{heading_key(by_id[record_id].section_path)}"
        for record_id in vectors.ids
        if by_id[record_id].source != "vsmart" and by_id[record_id].section_path
    }
    period_run = run_facet("period", vectors.ids, vectors.matrix, periods, held, [i for i in vectors.ids if not periods[i]])
    entry_run = run_facet("theme", vectors.ids, vectors.matrix, themes, held, [])
    heading_run = run_headings("theme", vectors.ids, vectors.matrix, themes, held, groups, [i for i in vectors.ids if not themes[i]])

    report = build / "facet_report.md"
    proposals = build / "heading_subject_proposals.csv"
    report.write_text(_report(records, themes, periods, period_run, entry_run, heading_run, groups), encoding="utf-8")
    examples: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        if record.id in groups and record.id in heading_run.suggestions:
            examples[groups[record.id]].append(record)
    with proposals.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["heading_key", "heading", "years", "n_entries", "proposed", "scores", "example_titles"])
        for key, members in sorted(examples.items(), key=lambda item: -len(item[1])):
            scores = heading_run.headings.get(key, {})
            proposed = sorted(heading_run.suggestions[members[0].id])
            years = sorted({member.bgb_year for member in members if member.bgb_year})
            writer.writerow([
                key,
                " > ".join(members[0].section_path[-2:]),
                f"{years[0]}–{years[-1]}" if years else "",
                len(members),
                " ".join(proposed),
                " ".join(f"{label}:{value:.2f}" for label, value in sorted(scores.items(), key=lambda item: -item[1])[:4]),
                " | ".join((member.title or "")[:80] for member in members[:3]),
            ])
    return [str(report), str(proposals)]


def _report(records, themes, periods, period_run, entry_run, heading_run, groups) -> str:
    old = [record for record in records if record.source != "vsmart" and (record.bgb_year or 0) < 1993]
    lines = [
        "# Facet values from neighbours in meaning (F3)",
        "",
        f"Entries: {len(records)}. With a checked subject area: {sum(1 for value in themes.values() if value)}; "
        f"with a checked period: {sum(1 for value in periods.values() if value)}. Held out: V-Smart 2015–2017 and print 2005–2008. "
        f"Neighbours: {K}, bge-m3 vectors of title, subtitle and translated title. A value is kept only where at least "
        f"{PRECISION:.0%} of its held-out suggestions are right.",
        "",
    ]
    for title, run in (("Period, per entry", period_run), ("Subject area, per entry", entry_run), ("Subject area, per printed heading", heading_run)):
        lines += [f"## {title}", ""]
        if run.thresholds:
            lines += ["| Value | Threshold | Held-out suggestions | Right |", "|---|---:|---:|---:|"]
            for label, (threshold, made, precision) in run.thresholds.items():
                lines.append(f"| {label} | {threshold:.2f} | {made} | {precision:.1%} |")
            combined = run.combined
            lines += ["", f"All values together: **{combined.precision:.1%}** right; {combined.coverage:.1%} of held-out entries get at least one value. "
                      f"Suggested for {len(run.suggestions)} entries without a checked value.", ""]
        else:
            best = max(run.curve, key=lambda point: point.precision)
            lines += [f"No value reaches {PRECISION:.0%}. Best: {best.precision:.1%} right at threshold {best.threshold:.2f}, "
                      f"for {best.coverage:.1%} of held-out entries.", ""]
    lines += ["## Coverage before 1993, per BGB year", "",
              "| Year | Entries | Subject area now | + headings | Period checked | + suggestions |", "|---|---:|---:|---:|---:|---:|"]
    by_year: dict[int, list[Record]] = defaultdict(list)
    for record in old:
        by_year[record.bgb_year].append(record)
    for year in sorted(by_year):
        members = by_year[year]
        now = sum(1 for record in members if record.theme)
        added = sum(1 for record in members if not record.theme and record.id in heading_run.suggestions)
        checked = sum(1 for record in members if periods.get(record.id))
        more = sum(1 for record in members if not periods.get(record.id) and record.id in period_run.suggestions)
        n = len(members)
        lines.append(f"| {year} | {n} | {now / n:.0%} | {(now + added) / n:.0%} | {checked / n:.0%} | {(checked + more) / n:.0%} |")
    lines += ["", "## Twenty headings with a proposal, at random", ""]
    picked: dict[str, list[Record]] = defaultdict(list)
    for record in old:
        if record.id in heading_run.suggestions and record.id in groups:
            picked[groups[record.id]].append(record)
    for key in random.Random(7).sample(sorted(picked), min(20, len(picked))):
        members = picked[key]
        lines.append(f"- **{' > '.join(members[0].section_path[-2:])}** ({len(members)} entries) → "
                     f"{', '.join(sorted(heading_run.suggestions[members[0].id]))}. "
                     + "; ".join(f"*{(member.title or '')[:70]}*" for member in members[:3]))
    return "\n".join(lines) + "\n"


def mark_origin(record: Record, theme_map: list[tuple[str, str]]) -> None:
    """Fill ``theme_suggested`` and ``period_suggested``: the values no person or printed volume gave."""
    themes = checked_themes(record, theme_map)
    periods = set(assign_period(record.section_path, checked_codes(record)))
    record.theme_suggested = [theme for theme in record.theme if theme not in themes]
    record.period_suggested = [period for period in record.period if period not in periods]


def apply_suggestions(records: list[Record], build_dir) -> dict[str, int]:
    """Add the suggested periods and subject areas to every entry, also beside values it already has, and mark
    which values are suggested. Subject areas come per printed heading and, where a title alone is clear enough,
    per entry; periods per entry. Each is kept only above its held-out 90 % threshold."""
    from pathlib import Path

    from bhb.categorise import heading_key
    from bhb.model import Category
    from bhb.scheme import load_theme_map
    from bhb.similar import DEFAULT_MODEL, encode

    theme_map = load_theme_map()
    entries = [record for record in records if record.role == "entry" and not record.is_cross_listing]
    vectors = encode(entries, DEFAULT_MODEL, Path(build_dir) / "vectors" / f"{DEFAULT_MODEL.replace('/', '__')}.npz")
    by_id = {record.id: record for record in entries}
    themes = {record_id: checked_themes(by_id[record_id], theme_map) for record_id in vectors.ids}
    periods = {record_id: checked_periods(by_id[record_id]) for record_id in vectors.ids}
    held = {record_id: held_out(by_id[record_id]) for record_id in vectors.ids}
    groups = {
        record_id: f"{'old' if (by_id[record_id].bgb_year or 0) < 1993 else 'new'}|{heading_key(by_id[record_id].section_path)}"
        for record_id in vectors.ids
        if by_id[record_id].source != "vsmart" and by_id[record_id].section_path
    }
    every = list(vectors.ids)
    period_run = run_facet("period", every, vectors.matrix, periods, held, every)
    entry_run = run_facet("theme", every, vectors.matrix, themes, held, every)
    heading_run = run_headings("theme", every, vectors.matrix, themes, held, groups, every)
    counts = {"themes_added": 0, "periods_added": 0, "entries_with_new_theme": 0, "entries_with_new_period": 0}
    for record_id, record in by_id.items():
        added = False
        for source, run in (("semantic-heading", heading_run), ("semantic", entry_run)):
            for theme in sorted(run.suggestions.get(record_id, set())):
                if theme in record.theme:
                    continue
                record.theme.append(theme)
                record.categories.append(
                    Category(code=None, source=source, confidence=0.9, machine=True, primary=not record.categories, theme=theme)
                )
                counts["themes_added"] += 1
                added = True
        counts["entries_with_new_theme"] += added
        new_periods = [period for period in sorted(period_run.suggestions.get(record_id, set())) if period not in record.period]
        record.period.extend(new_periods)
        counts["periods_added"] += len(new_periods)
        counts["entries_with_new_period"] += bool(new_periods)
    for record in records:
        mark_origin(record, theme_map)
    return counts
