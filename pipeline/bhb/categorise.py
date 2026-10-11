"""One category for every entry: a reviewed heading, a V-Smart code, or the classifier.

Nothing below the confidence floor is stored. ``bhb categorise draft`` refreshes proposals and
does not change a filled ``approved_code``, ``approved_theme`` or ``reviewer`` cell.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from bhb.facets import assign_period, periods_from_codes, periods_from_path
from bhb.model import Category, Record
from bhb.paths import build_dir, repo_root
from bhb.scheme import (
    _dutch_half,
    _french_half,
    agreement_score,
    code_from_path,
    load_scheme,
    load_theme_map,
    parent_code,
    themes_for_code,
    truncate_code,
)
from bhb.textutil import fold

TAU_CODE = 0.70
TAU_THEME_FLOOR = 0.60
HEADING_MIN_PROB = 0.50
HEADING_MIN_N = 5
CROSSWALK_USE = 0.80
LABEL_AGREE = 70
MIN_CLASS = 30
WORD_FEATURES = 100_000
CHAR_FEATURES = 80_000
TEXT_CAP = 4_000

COLUMNS = (
    "era",
    "heading_key",
    "example_fr",
    "example_nl",
    "years",
    "n_entries",
    "proposed_code",
    "proposed_by",
    "proposal_confidence",
    "second_code",
    "second_confidence",
    "approved_code",
    "approved_theme",
    "reviewer",
    "note",
)
PROTECTED = ("approved_code", "approved_theme", "reviewer")

_RANGE = re.compile(r"\b\d{3,4}\s*[–—-]\s*\d{2,4}\b")
_RANGE_FOLDED = re.compile(r"\b\d{3,4}\s+\d{2,4}\b")
_FOOTNOTE = re.compile(r"\(\d{1,2}\)")


@dataclass
class Scored:
    code: str | None
    code_p: float
    themes: list[tuple[str, float]] = field(default_factory=list)


def crosswalk_path() -> Path:
    return repo_root() / "data" / "curated" / "heading_crosswalk.csv"


def heading_key(section_path: list[str]) -> str:
    """Accent-folded French half, with footnote marks, date ranges and spaces removed."""
    return "".join(normalise_heading(heading) for heading in section_path)


def normalise_heading(heading: str) -> str:
    """French half of one heading, folded, ready to be joined into a key."""
    # A date range uses the same dash as a bilingual heading, so remove it first.
    heading = _RANGE.sub(" ", heading)
    half = _FOOTNOTE.sub(" ", _french_half(heading))
    folded = _RANGE_FOLDED.sub(" ", fold(half))
    return re.sub(r"\s+", "", folded)


def era_of(years: set[int]) -> str:
    if not years:
        return ""
    if min(years) >= 1993:
        return "1993-2008"
    if max(years) <= 1961:
        return "1952-1961"
    return "1962-1992"


def document_text(record: Record) -> str:
    """Title, subtitle, translation, host title and note. Not the heading."""
    host = record.host.title if record.host and record.host.title else ""
    parts = [record.title, record.subtitle, record.title_translated, host, record.note]
    text = " ".join(part.strip() for part in parts if part and part.strip())
    return text[:TEXT_CAP]


def refresh_crosswalk(proposed: list[dict], existing: list[dict]) -> list[dict]:
    """Copy filled review cells onto the new proposals. Empty cells stay empty."""
    previous = {row["heading_key"]: row for row in existing if row.get("heading_key")}
    for row in proposed:
        old = previous.get(row["heading_key"])
        if not old:
            continue
        for column in PROTECTED:
            if str(old.get(column) or "").strip():
                row[column] = old[column]
    return proposed


def choose_tau_theme(scored: list[tuple[dict[str, float], set[str]]]) -> tuple[float, float | None, float]:
    """Smallest tau >= 0.60 with at least 90% precision. Returns tau, precision, coverage."""
    chosen: tuple[float, float, float] | None = None
    best: tuple[float, float, float] | None = None
    for step in range(60, 100):
        tau = step / 100
        precision, coverage = theme_stats(scored, tau)
        if precision is None:
            continue
        if best is None or precision > best[1] or (precision == best[1] and tau > best[0]):
            best = (tau, precision, coverage)
        if precision >= 0.90 and chosen is None:
            chosen = (tau, precision, coverage)
    if chosen:
        return chosen
    if best:
        return best
    return TAU_THEME_FLOOR, None, 0.0


def theme_stats(scored: list[tuple[dict[str, float], set[str]]], tau: float) -> tuple[float | None, float]:
    predicted = correct = covered = 0
    for probs, truth in scored:
        hit = False
        for theme, probability in probs.items():
            if probability < tau:
                continue
            predicted += 1
            hit = True
            if theme in truth:
                correct += 1
        if hit:
            covered += 1
    precision = correct / predicted if predicted else None
    coverage = covered / len(scored) if scored else 0.0
    return precision, coverage


def categories_for(
    record: Record,
    row: dict | None,
    secondary_rows: list[dict],
    scored: Scored | None,
    tau_code: float,
    tau_theme: float,
) -> list[Category]:
    """Precedence in the plan: approved, V-Smart, see-also, unreviewed proposal, classifier."""
    categories: list[Category] = []
    primary = False

    def add(
        code: str | None,
        source: str,
        confidence: float,
        machine: bool,
        *,
        theme: str | None = None,
        as_primary: bool = False,
    ) -> None:
        nonlocal primary
        use_primary = as_primary and not primary
        if use_primary:
            primary = True
        categories.append(
            Category(
                code=code or None,
                source=source,
                confidence=round(float(confidence), 4),
                machine=machine,
                primary=use_primary,
                theme=theme,
            )
        )

    approved = (row.get("approved_code") or "").strip() if row else ""
    approved_theme = (row.get("approved_theme") or "").strip() if row else ""
    reviewer = (row.get("reviewer") or "").strip() if row else ""
    broad = approved.upper() == "BROAD"
    source = "heading-rule" if reviewer == "rule" else "crosswalk"
    if approved and not broad:
        add(approved, source, 1.0, False, as_primary=True)
        if approved_theme:
            add(None, source, 1.0, False, theme=approved_theme)
    elif approved_theme and not broad:
        add(None, source, 1.0, False, theme=approved_theme, as_primary=True)

    for index, code in enumerate(record.bhb_codes):
        add(code, "vsmart", 1.0, False, as_primary=not primary and index == 0)

    for other in secondary_rows:
        resolved = _resolved(other)
        if resolved:
            code, confidence, machine = resolved
            add(code, "see-also", confidence, machine)

    if not primary and row and not broad:
        proposed = (row.get("proposed_code") or "").strip()
        confidence = _float(row.get("proposal_confidence"))
        if proposed and confidence >= CROSSWALK_USE:
            add(proposed, "crosswalk", confidence, True, as_primary=True)

    if not primary and scored is not None:
        if scored.code and scored.code_p >= tau_code:
            add(scored.code, "classifier", scored.code_p, True, as_primary=True)
        else:
            first = True
            for theme, probability in sorted(scored.themes, key=lambda item: -item[1]):
                if probability < tau_theme:
                    continue
                add(None, "classifier", probability, True, theme=theme, as_primary=first)
                first = False
    return categories


def themes_of(categories: list[Category], theme_map: list[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    for category in categories:
        if category.code:
            found.extend(themes_for_code(category.code, theme_map))
        elif category.theme:
            found.append(category.theme)
    return list(dict.fromkeys(found))


def categorise(
    records: list[Record],
    *,
    tau_code: float | None = None,
    tau_theme: float | None = None,
) -> dict:
    """Fill ``categories``, ``theme`` and ``period``, and write the crosswalk and the report."""
    code_tau = TAU_CODE if tau_code is None else tau_code
    theme_tau = tau_theme
    if theme_tau is not None and theme_tau < TAU_THEME_FLOOR:
        print(f"tau_theme {theme_tau} is below {TAU_THEME_FLOOR}; using {TAU_THEME_FLOOR}")
        theme_tau = TAU_THEME_FLOOR

    scheme = load_scheme()
    theme_map = load_theme_map()
    existing = read_crosswalk(crosswalk_path())
    groups = _groups(records)
    proposed = [_number_row(group, scheme) for group in groups.values()]
    by_key = {row["heading_key"]: row for row in proposed}
    # Training must see a reviewer's code. The file on disk wins over a fresh rule.
    training_rows = refresh_crosswalk([dict(row) for row in proposed], existing)

    model, classes, heldout, trained = _fit(records, training_rows, by_key, theme_map)
    metrics: dict = {"trained": trained, "tau_code": code_tau}
    if model is not None and heldout:
        raw = _predict(model, [item[0] for item in heldout])
        theme_cases, code_hits, code_tried, code_ps = _heldout_scores(raw, classes, heldout, theme_map, code_tau)
        if theme_tau is None:
            theme_tau, theme_precision, theme_coverage = choose_tau_theme(theme_cases)
        else:
            theme_precision, theme_coverage = theme_stats(theme_cases, theme_tau)
        code_precision = code_hits / code_tried if code_tried else None
        either = sum(
            1
            for code_p, (probs, _truth) in zip(code_ps, theme_cases)
            if code_p >= code_tau or any(probability >= theme_tau for probability in probs.values())
        )
        metrics.update(
            heldout=len(heldout),
            tau_theme=theme_tau,
            theme_precision=theme_precision,
            theme_coverage=theme_coverage,
            code_precision=code_precision,
            code_coverage=code_tried / len(heldout) if heldout else 0.0,
            either_coverage=either / len(heldout) if heldout else 0.0,
        )
    else:
        theme_tau = theme_tau if theme_tau is not None else TAU_THEME_FLOOR
        metrics.update(
            heldout=0,
            tau_theme=theme_tau,
            theme_precision=None,
            theme_coverage=0.0,
            code_precision=None,
            code_coverage=0.0,
            either_coverage=0.0,
        )
        if model is None:
            print("classifier unavailable; only heading rules and V-Smart codes are applied")

    refresh_crosswalk(list(by_key.values()), existing)
    scored = (
        _apply_model(records, groups, by_key, model, classes, theme_map, theme_tau)
        if model is not None
        else {}
    )
    final = refresh_crosswalk(list(by_key.values()), existing)
    final.sort(key=lambda row: (-int(row["n_entries"]), row["heading_key"]))
    write_crosswalk(final, crosswalk_path())
    _apply(records, by_key, scored, theme_map, code_tau, theme_tau)
    report = _report(records, final, metrics)
    destination = build_dir() / "classification_report.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report, encoding="utf-8")
    print(f"crosswalk: {len(final)} headings → {crosswalk_path()}")
    print(f"report: {destination}")
    return metrics


def read_crosswalk(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_crosswalk(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COLUMNS})


@dataclass
class _Group:
    key: str
    paths: Counter = field(default_factory=Counter)
    years: set[int] = field(default_factory=set)
    n_entries: int = 0


def _groups(records: list[Record]) -> dict[str, _Group]:
    groups: dict[str, _Group] = {}
    for record in records:
        if not _print_entry(record) or not record.section_path:
            continue
        key = heading_key(record.section_path)
        if not key:
            continue
        group = groups.get(key)
        if group is None:
            group = _Group(key=key)
            groups[key] = group
        group.paths[tuple(record.section_path)] += 1
        if record.bgb_year:
            group.years.add(record.bgb_year)
        group.n_entries += 1
    return groups


def _number_row(group: _Group, scheme: dict) -> dict:
    path = list(group.paths.most_common(1)[0][0])
    numbered = [heading for heading in path if code_from_path([heading])]
    heading = numbered[-1] if numbered else (path[-1] if path else "")
    code = code_from_path(path) or ""
    modern = bool(group.years) and min(group.years) >= 1993
    score = agreement_score(heading, code, scheme) if modern and code else 0.0
    agreed = modern and bool(code) and score >= LABEL_AGREE
    row = _blank(group, path)
    # Numbers from before 1993 belong to an older scheme, so they are not proposed as modern codes.
    if modern and code:
        row["proposed_code"] = code
        row["proposed_by"] = "numbers+label" if agreed else "numbers"
        row["proposal_confidence"] = f"{score / 100:.4f}"
    if agreed:
        row["approved_code"] = code
        row["reviewer"] = "rule"
    return row


def _blank(group: _Group, path: list[str]) -> dict:
    return {
        "era": era_of(group.years),
        "heading_key": group.key,
        "example_fr": " / ".join(_clean_half(_french_half(heading)) for heading in path if _french_half(heading)),
        "example_nl": " / ".join(_clean_half(_dutch_half(heading)) for heading in path if _dutch_half(heading)),
        "years": " ".join(str(year) for year in sorted(group.years)),
        "n_entries": str(group.n_entries),
        "proposed_code": "",
        "proposed_by": "",
        "proposal_confidence": "",
        "second_code": "",
        "second_confidence": "",
        "approved_code": "",
        "approved_theme": "",
        "reviewer": "",
        "note": "",
    }


def _fit(records, training_rows, by_key, theme_map):
    """Return model, class list, held-out rows, and whether a model was trained."""
    approved = {row["heading_key"]: (row.get("approved_code") or "").strip() for row in training_rows}
    train_text: list[str] = []
    train_label: list[str] = []
    heldout: list[tuple[str, str, set[str]]] = []
    for record in records:
        if record.role != "entry" or record.is_cross_listing:
            continue
        text = document_text(record)
        if not text:
            continue
        year = record.bgb_year or 0
        if record.source == "vsmart" and record.bhb_codes:
            label = truncate_code(record.bhb_codes[0])
            themes = set(themes_for_code(record.bhb_codes[0], theme_map))
            if 2009 <= year <= 2014:
                train_text.append(text)
                train_label.append(label)
            elif 2015 <= year <= 2017:
                heldout.append((text, label, themes))
            continue
        if not _print_entry(record):
            continue
        code = approved.get(heading_key(record.section_path), "")
        if not code or code.upper() == "BROAD":
            continue
        label = truncate_code(code)
        themes = set(themes_for_code(code, theme_map))
        if 1993 <= year <= 2004:
            train_text.append(text)
            train_label.append(label)
        elif 2005 <= year <= 2008:
            heldout.append((text, label, themes))
    mapping = _collapse(train_label)
    paired = [(text, mapping[label]) for text, label in zip(train_text, train_label) if label in mapping]
    if len({label for _, label in paired}) < 2:
        return None, [], heldout, 0
    texts = [text for text, _label in paired]
    labels = [label for _text, label in paired]
    model = _train(texts, labels)
    classes = list(model.named_steps["clf"].classes_)
    print(f"classifier: {len(texts)} training entries, {len(classes)} codes, {len(heldout)} held out")
    return model, classes, heldout, len(texts)


def _collapse(labels: list[str]) -> dict[str, str]:
    counts = Counter(labels)
    while True:
        rare = [code for code, count in counts.items() if count < MIN_CLASS and parent_code(code)]
        if not rare:
            break
        for code in rare:
            parent = parent_code(code)
            counts[parent] = counts.get(parent, 0) + counts.pop(code)
    surviving = {code for code, count in counts.items() if count >= MIN_CLASS}
    mapping: dict[str, str] = {}
    for code in set(labels):
        current = code
        while current not in surviving and parent_code(current):
            current = parent_code(current)
        if current in surviving:
            mapping[code] = current
    return mapping


def _train(texts: list[str], labels: list[str]):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline

    word = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2, max_features=WORD_FEATURES)
    char = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2, max_features=CHAR_FEATURES
    )
    classifier = LogisticRegression(solver="saga", max_iter=30, tol=1e-3, random_state=0)
    model = Pipeline([
        ("features", FeatureUnion([("word", word), ("char", char)])),
        ("clf", classifier),
    ])
    model.fit(texts, labels)
    return model


def _predict(model, texts: list[str]):
    import numpy as np

    if not texts:
        return np.zeros((0, 0))
    chunks = []
    step = 4000
    for start in range(0, len(texts), step):
        chunks.append(model.predict_proba(texts[start : start + step]))
        print(f"  predicted {min(start + step, len(texts))}/{len(texts)}", flush=True)
    return np.vstack(chunks)


def _heldout_scores(raw, classes, heldout, theme_map, tau_code):
    import numpy as np

    class_themes = [themes_for_code(code, theme_map) for code in classes]
    cases: list[tuple[dict[str, float], set[str]]] = []
    known = set(classes)
    code_hits = code_tried = 0
    code_ps: list[float] = []
    for vector, (_text, label, truth) in zip(raw, heldout):
        cases.append((_theme_vector(vector, class_themes), truth))
        winner = int(np.argmax(vector))
        code_ps.append(float(vector[winner]))
        if float(vector[winner]) >= tau_code:
            code_tried += 1
            if classes[winner] == _project(label, known):
                code_hits += 1
    return cases, code_hits, code_tried, code_ps


def _project(label: str, classes: set[str]) -> str:
    """Walk up to the class the training collapse would actually predict."""
    current = label
    while current not in classes:
        parent = parent_code(current)
        if not parent:
            return label
        current = parent
    return current


def _apply_model(records, groups, by_key, model, classes, theme_map, tau_theme) -> dict[str, Scored]:
    """One prediction pass: heading proposals for 1952–1992, then scores for the rest."""
    import numpy as np

    targets: list[tuple[Record, str, bool]] = []
    for record in records:
        if record.role != "entry" or record.is_cross_listing or (record.source == "vsmart" and record.bhb_codes):
            continue
        text = document_text(record)
        if not text:
            continue
        key = heading_key(record.section_path) if record.section_path else ""
        group = groups.get(key)
        old = bool(group and group.years and min(group.years) < 1993)
        if old or not _accepted(by_key.get(key)):
            targets.append((record, key, old))
    if not targets:
        return {}
    print(f"scoring {len(targets)} print entries")
    raw = _predict(model, [document_text(record) for record, _key, _old in targets])
    masks = _masks(classes)
    class_themes = [themes_for_code(code, theme_map) for code in classes]
    sums: dict[str, np.ndarray] = {}
    counts: dict[str, int] = defaultdict(int)
    heading_periods: dict[str, list[str]] = {}
    for (record, key, old), vector in zip(targets, raw):
        if not old:
            continue
        if key not in heading_periods:
            heading_periods[key] = periods_from_path(record.section_path)
        masked = _masked(vector, masks, heading_periods[key])
        if masked is None:
            continue
        bucket = sums.get(key)
        if bucket is None:
            sums[key] = masked.copy()
        else:
            bucket += masked
        counts[key] += 1
    for key, total in sums.items():
        count = counts[key]
        if count < HEADING_MIN_N:
            continue
        mean = total / count
        order = np.argsort(mean)[::-1]
        best = int(order[0])
        if float(mean[best]) < HEADING_MIN_PROB:
            continue
        row = by_key.get(key)
        if row is None:
            continue
        row["proposed_code"] = classes[best]
        row["proposed_by"] = "classifier"
        row["proposal_confidence"] = f"{float(mean[best]):.4f}"
        if len(order) > 1 and float(mean[int(order[1])]) > 0:
            row["second_code"] = classes[int(order[1])]
            row["second_confidence"] = f"{float(mean[int(order[1])]):.4f}"
    scored: dict[str, Scored] = {}
    for (record, key, _old), vector in zip(targets, raw):
        if _accepted(by_key.get(key)):
            continue
        masked = _masked(vector, masks, periods_from_path(record.section_path))
        if masked is None:
            continue
        winner = int(np.argmax(masked))
        themes = [
            (name, probability)
            for name, probability in _theme_vector(masked, class_themes).items()
            if probability >= tau_theme
        ]
        scored[record.id] = Scored(classes[winner], float(masked[winner]), themes)
    return scored


def _apply(records, by_key, scored, theme_map, tau_code, tau_theme) -> None:
    rows = by_key
    for record in records:
        if record.role != "entry" or record.is_cross_listing:
            continue
        row = rows.get(heading_key(record.section_path)) if record.section_path else None
        secondary = []
        for path in record.secondary_sections:
            other = rows.get(heading_key(path))
            if other is not None:
                secondary.append(other)
        categories = categories_for(record, row, secondary, scored.get(record.id), tau_code, tau_theme)
        record.categories = categories
        record.theme = themes_of(categories, theme_map)
        codes = [category.code for category in categories if category.code]
        record.period = assign_period(record.section_path, codes or record.bhb_codes)


def _report(records: list[Record], rows: list[dict], metrics: dict) -> str:
    buckets: dict[tuple[int, str], Counter] = defaultdict(Counter)
    for record in records:
        if record.role != "entry" or record.is_cross_listing or not record.bgb_year:
            continue
        bucket = buckets[(record.bgb_year, record.source)]
        bucket["entries"] += 1
        kind = _origin(record)
        bucket[kind] += 1
        if record.theme:
            bucket["themed"] += 1
    lines = [
        "# Classification",
        "",
        f"Code threshold: {metrics['tau_code']:.2f}. Theme threshold: {metrics['tau_theme']:.2f}.",
        f"Training entries: {metrics['trained']}. Held-out entries: {metrics['heldout']}.",
        "",
        _metric("Held-out code precision", metrics.get("code_precision")),
        _metric("Held-out code coverage", metrics.get("code_coverage")),
        _metric("Held-out theme precision", metrics.get("theme_precision")),
        _metric("Held-out theme coverage", metrics.get("theme_coverage")),
        _metric("Held-out entries with a code or a theme", metrics.get("either_coverage")),
        "",
        "Target: at least 90% of entries with a theme in every year, and at most 25% of those themes machine-derived.",
        "",
        "| Year | Source | Entries | With a theme | Person | Rule | V-Smart | Machine | Unclassified | Machine share |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for (year, source), bucket in sorted(buckets):
        themed = bucket["themed"]
        share = bucket["machine"] / themed if themed else 0
        lines.append(
            f"| {year} | {source} | {bucket['entries']} | {themed / bucket['entries']:.1%} "
            f"| {bucket['person']} | {bucket['rule']} | {bucket['vsmart']} | {bucket['machine']} "
            f"| {bucket['unclassified']} | {share:.1%} |"
        )
    covered = sum(int(row["n_entries"]) for row in rows[:100])
    total = sum(int(row["n_entries"]) for row in rows)
    lines.extend(
        [
            "",
            f"Crosswalk rows: {len(rows)}. The first 100 cover {covered} of {total} print entries "
            f"({covered / total:.1%})." if total else f"Crosswalk rows: {len(rows)}.",
            "",
        ]
    )
    return "\n".join(lines)


def _origin(record: Record) -> str:
    if not record.theme:
        return "unclassified"
    primary = next((category for category in record.categories if category.primary), None)
    chosen = primary or (record.categories[0] if record.categories else None)
    if chosen is None or chosen.machine:
        return "machine" if chosen is not None else "unclassified"
    if chosen.source == "vsmart":
        return "vsmart"
    if chosen.source in {"heading-rule", "see-also"}:
        return "rule"
    return "person"


def _accepted(row: dict | None) -> bool:
    if not row:
        return False
    approved = (row.get("approved_code") or "").strip()
    if approved.upper() == "BROAD":
        return False
    if approved or (row.get("approved_theme") or "").strip():
        return True
    return bool((row.get("proposed_code") or "").strip()) and _float(row.get("proposal_confidence")) >= CROSSWALK_USE


def _resolved(row: dict) -> tuple[str, float, bool] | None:
    approved = (row.get("approved_code") or "").strip()
    if approved and approved.upper() != "BROAD":
        return approved, 1.0, False
    if approved.upper() == "BROAD":
        return None
    proposed = (row.get("proposed_code") or "").strip()
    confidence = _float(row.get("proposal_confidence"))
    if proposed and confidence >= CROSSWALK_USE:
        return proposed, confidence, True
    return None


def _masks(classes: list[str]) -> dict[str, list[int]]:
    masks: dict[str, list[int]] = {}
    periods = ("aux", "general", "ancient", "medieval", "burgundian", "early-modern", "contemporary")
    for period in periods:
        masks[period] = [1 if period in periods_from_codes([code]) else 0 for code in classes]
    return masks


def _masked(vector, masks, periods: list[str]):
    import numpy as np

    if not periods:
        return vector
    mask = np.zeros(len(vector))
    for period in periods:
        row = masks.get(period)
        if row:
            mask = np.maximum(mask, np.asarray(row))
    kept = vector * mask
    total = float(kept.sum())
    if total <= 0:
        return None
    return kept / total


def _theme_vector(vector, class_themes: list[list[str]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for probability, names in zip(vector, class_themes):
        if probability < 1e-6:
            continue
        for name in names:
            totals[name] = totals.get(name, 0.0) + float(probability)
    return totals


def _print_entry(record: Record) -> bool:
    return record.role == "entry" and not record.is_cross_listing and record.source.startswith("print")


def _clean_half(text: str) -> str:
    return _FOOTNOTE.sub("", text).strip(" .")


def _float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _metric(label: str, value: float | None) -> str:
    if value is None:
        return f"{label}: —"
    return f"{label}: {value:.1%}"
