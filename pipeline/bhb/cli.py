"""Command line for the BHB-BGB pipeline.

    bhb ingest straive
    bhb ingest pdfvol
    bhb ingest vsmart
    bhb merge
    bhb build
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from bhb.gold import format_score, load_gold, score_records, write_sample
from bhb.ingest.jats import load_jats, straive_paths
from bhb.ingest.pdf_volume import convert_pdf
from bhb.ingest.vsmart import load_vsmart
from bhb.io_utils import read_jsonl, write_jsonl
from bhb.merge import heading_warnings, merge_records, write_report, write_scheme
from bhb.mods import export_mods
from bhb.model import Record
from bhb.paths import build_dir, raw_root, repo_root
from bhb.release import release_command, write_release


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bhb", description="Bibliography of Belgian History pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="read one source into JSON Lines")
    ingest_sub = ingest.add_subparsers(dest="source", required=True)
    straive = ingest_sub.add_parser("straive", help="STRAIVE JATS, 1952–1963 and 1966–2007")
    straive.add_argument("--out", type=Path)
    pdfvol = ingest_sub.add_parser("pdfvol", help="1964, 1965 and 2008 from PDF")
    pdfvol.add_argument("--out", type=Path)
    pdfvol.add_argument("--skip-convert", action="store_true", help="do not rebuild BGB_2008.xml")
    vsmart = ingest_sub.add_parser("vsmart", help="State Archives exports, 2009–2017")
    vsmart.add_argument("--out", type=Path)

    merge = sub.add_parser("merge", help="combine the three JSON Lines files")
    merge.add_argument("--out", type=Path)
    sub.add_parser("build", help="ingest every source, merge, and categorise")

    categorise = sub.add_parser("categorise", help="assign period and theme")
    categorise_sub = categorise.add_subparsers(dest="categorise_command", required=True)
    draft = categorise_sub.add_parser("draft", help="refresh heading proposals and categorise the built records")
    draft.add_argument("--tau-code", type=float)
    draft.add_argument("--tau-theme", type=float)
    draft.add_argument("--records", type=Path)

    gold = sub.add_parser("gold", help="sample entries for correction, or score a corrected sheet")
    gold_sub = gold.add_subparsers(dest="gold_command", required=True)
    sample = gold_sub.add_parser("sample", help="write a stratified sample of print entries")
    sample.add_argument("--n", type=int, default=300)
    sample.add_argument("--seed", type=int, default=2026)
    sample.add_argument("--out", type=Path)
    score = gold_sub.add_parser("score", help="field accuracy against a corrected sheet")
    score.add_argument("--gold", type=Path, nargs="*", help="defaults to the intern 1992 sheets")

    export = sub.add_parser("export", help="write the semantic record out for archive and exchange")
    export_sub = export.add_subparsers(dest="export_command", required=True)
    mods = export_sub.add_parser("mods", help="MODS 3.8, one collection per BGB year")
    mods.add_argument("--out", type=Path)
    skos = export_sub.add_parser("skos", help="the BHB scheme, periods and themes as SKOS (Turtle)")
    skos.add_argument("--out", type=Path)

    similar = sub.add_parser("similar", help="embed every entry and store its nearest neighbours (needs the embed extra)")
    similar.add_argument("--model", default=None, help="sentence-transformers model name")
    similar.add_argument("--k", type=int, default=None, help="neighbours per record")
    similar.add_argument("--batch-size", type=int, default=128)
    similar.add_argument("--records", type=Path)

    facets = sub.add_parser("facets", help="facet values from neighbours in meaning (needs the embed extra)")
    facets_sub = facets.add_subparsers(dest="facets_command", required=True)
    facets_sub.add_parser("suggest", help="measure on held-out years; write build/facet_report.md and a review file")
    facets_sub.add_parser("apply", help="add suggested periods and subject areas to build/records.jsonl, marked as suggested")

    places = sub.add_parser("places", help="places of the printed place indexes (1993–2007)")
    places_sub = places.add_subparsers(dest="places_command", required=True)
    places_sub.add_parser("apply", help="write the indexed places into build/records.jsonl")

    release = sub.add_parser("release", help="pack the derived dataset for a GitHub release")
    release.add_argument("--records", type=Path)
    release.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    if args.command == "build":
        build()
        return
    if args.command == "categorise" and args.categorise_command == "draft":
        _categorise_draft(args.tau_code, args.tau_theme, args.records)
        return
    if args.command == "places" and args.places_command == "apply":
        from bhb.places import apply_places

        path = build_dir() / "records.jsonl"
        records = read_jsonl(path)
        counts = apply_places(records, raw_root())
        write_jsonl(path, records)
        print(f"places: {counts} → {path}")
        return
    if args.command == "facets" and args.facets_command == "apply":
        from bhb.facet_suggest import apply_suggestions

        path = build_dir() / "records.jsonl"
        records = read_jsonl(path)
        counts = apply_suggestions(records, build_dir())
        write_jsonl(path, records)
        print(f"facets: {counts} → {path}")
        return
    if args.command == "facets" and args.facets_command == "suggest":
        from bhb.facet_suggest import suggest_command

        for written in suggest_command(build_dir() / "records.jsonl", build_dir()):
            print(f"facets: {written}")
        return
    if args.command == "export" and args.export_command == "skos":
        from bhb.skos import write_skos

        destination = args.out or build_dir() / "skos" / "bhb.ttl"
        counts = write_skos(destination)
        print(f"skos: {counts['codes']} codes, {counts['periods']} periods, {counts['themes']} themes, {counts['facet_links']} facet links → {destination}")
        return
    if args.command == "export" and args.export_command == "mods":
        source = build_dir() / "records.jsonl"
        if not source.is_file():
            raise SystemExit("build/records.jsonl is missing; run bhb build first")
        destination = args.out or build_dir() / "mods"
        counts = export_mods(source, destination)
        total = sum(counts.values())
        print(f"mods: {total} records in {len(counts)} files → {destination}")
        return
    if args.command == "similar":
        _similar(args.model, args.k, args.batch_size, args.records)
        return
    if args.command == "release":
        records = args.records or build_dir() / "records.jsonl"
        destination = args.out or build_dir() / "release"
        try:
            notes = write_release(records, destination)
        except FileNotFoundError as error:
            raise SystemExit(str(error)) from error
        print(f"release: {notes.parent / 'records.jsonl.gz'}")
        print(release_command(date.today().isoformat()))
        return
    if args.command == "ingest" and args.source == "straive":
        records = ingest_straive()
        count = write_jsonl(args.out or build_dir() / "straive.jsonl", records)
        print(f"straive: {count} records")
        return
    if args.command == "ingest" and args.source == "pdfvol":
        records = ingest_pdf(convert=not args.skip_convert)
        count = write_jsonl(args.out or build_dir() / "pdfvol.jsonl", records)
        print(f"pdfvol: {count} records")
        return
    if args.command == "ingest" and args.source == "vsmart":
        records, labels = ingest_vsmart_records()
        count = write_jsonl(args.out or build_dir() / "vsmart.jsonl", records)
        _write_labels(labels)
        print(f"vsmart: {count} records, {len(labels)} classification codes")
        return
    if args.command == "merge":
        merged, labels = _merge_from_disk()
        _emit(merged, labels, args.out)
        return
    if args.command == "gold" and args.gold_command == "sample":
        _gold_sample(args.n, args.seed, args.out)
        return
    if args.command == "gold" and args.gold_command == "score":
        _gold_score(args.gold)
        return
    parser.error(f"unknown command {args.command}")


def build() -> list[Record]:
    straive = ingest_straive()
    write_jsonl(build_dir() / "straive.jsonl", straive)
    pdf = ingest_pdf(convert=True)
    write_jsonl(build_dir() / "pdfvol.jsonl", pdf)
    vsmart, labels = ingest_vsmart_records()
    write_jsonl(build_dir() / "vsmart.jsonl", vsmart)
    _write_labels(labels)
    merged, labels = merge_records(straive, pdf, vsmart, labels)
    from bhb.categorise import categorise

    print("categorise…")
    categorise(merged)
    from bhb.facet_suggest import mark_origin
    from bhb.scheme import load_theme_map

    theme_map = load_theme_map()
    for record in merged:
        mark_origin(record, theme_map)
    _emit(merged, labels, None)
    return merged


def ingest_straive() -> list[Record]:
    records: list[Record] = []
    for path in straive_paths(raw_root()):
        year_records = load_jats(path, "print-straive")
        print(f"  {path.name}: {len(year_records)}")
        records.extend(year_records)
    return records


def ingest_pdf(convert: bool = True) -> list[Record]:
    interim = raw_root() / "data" / "interim" / "print-pdf"
    pdf = raw_root() / "data" / "raw" / "pdf" / "BGB_2008.pdf"
    # A regenerated 2008 file is derived, so it is written under build/ and the raw copy stays untouched.
    generated = build_dir() / "print-pdf" / "BGB_2008.xml"
    if convert and pdf.is_file():
        generated.parent.mkdir(parents=True, exist_ok=True)
        report = convert_pdf(pdf, generated, "2008")
        print(f"  2008 PDF: {report['entries']} entries ({report['first']}–{report['last']})")
    elif not (interim / "BGB_2008.xml").is_file() and not generated.is_file():
        print("  2008 PDF not found and no BGB_2008.xml yet; that year is skipped")
    records: list[Record] = []
    for name in ("BGB_1964.xml", "BGB_1965.xml", "BGB_2008.xml"):
        path = generated if name == "BGB_2008.xml" and generated.is_file() else interim / name
        if not path.is_file():
            print(f"  missing {path.name}")
            continue
        year_records = load_jats(path, "print-pdf")
        print(f"  {path.name}: {len(year_records)}")
        records.extend(year_records)
    return records


def ingest_vsmart_records() -> tuple[list[Record], dict]:
    directory = raw_root() / "exports Rijksarchief"
    return load_vsmart(directory)


def _merge_from_disk() -> tuple[list[Record], dict]:
    folder = build_dir()
    labels: dict = {}
    label_path = folder / "bhb_codes.json"
    if label_path.is_file():
        labels = json.loads(label_path.read_text(encoding="utf-8"))
    return merge_records(
        read_jsonl(folder / "straive.jsonl"),
        read_jsonl(folder / "pdfvol.jsonl"),
        read_jsonl(folder / "vsmart.jsonl"),
        labels,
    )


def _categorise_draft(tau_code: float | None, tau_theme: float | None, records_path: Path | None) -> None:
    from bhb.categorise import categorise

    path = records_path or build_dir() / "records.jsonl"
    if not path.is_file():
        raise SystemExit("build/records.jsonl is missing; run bhb build first")
    records = read_jsonl(path)
    categorise(records, tau_code=tau_code, tau_theme=tau_theme)
    count = write_jsonl(path, records)
    print(f"categorise: {count} records → {path}")


def _gold_sample(n: int, seed: int, out: Path | None) -> None:
    records = _load_built_records()
    destination = out or repo_root() / "data" / "curated" / "gold" / "sample.xlsx"
    count = write_sample(records, destination, n=n, seed=seed)
    print(f"sample: {count} print entries → {destination}")


def _gold_score(paths: list[Path] | None) -> None:
    gold = load_gold(paths or None)
    records = _load_built_records()
    text = format_score(score_records(records, gold))
    print(text)
    report = build_dir() / "gold_score.md"
    report.write_text("# Gold-standard score\n\n" + text, encoding="utf-8")
    print(f"wrote {report}")


def _load_built_records() -> list[Record]:
    path = build_dir() / "records.jsonl"
    if not path.is_file():
        raise SystemExit("build/records.jsonl is missing; run bhb build first")
    return read_jsonl(path)


def _similar(model_name: str | None, k: int | None, batch_size: int, records_path: Path | None) -> None:
    from bhb.similar import DEFAULT_K, DEFAULT_MODEL, apply, encode, neighbours, write_report

    path = records_path or build_dir() / "records.jsonl"
    if not path.is_file():
        raise SystemExit(f"{path} is missing; run bhb build first")
    model_name = model_name or DEFAULT_MODEL
    records = read_jsonl(path)
    cache = build_dir() / "vectors" / f"{model_name.replace('/', '__')}.npz"
    vectors = encode(records, model_name, cache, batch_size)
    found = neighbours(vectors, k or DEFAULT_K)
    count = apply(records, found)
    write_jsonl(path, records)
    report = build_dir() / f"similar_report.{model_name.replace('/', '__')}.md"
    write_report(report, records, vectors, found, model_name)
    print(f"similar: {count} entries with neighbours → {path}")
    print(f"report: {report}")


def _write_labels(labels: dict) -> None:
    path = build_dir() / "bhb_codes.json"
    path.write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")


def _emit(records: list[Record], labels: dict, out: Path | None) -> None:
    destination = out or build_dir() / "records.jsonl"
    count = write_jsonl(destination, records)
    write_report(build_dir() / "ingest_report.md", records)
    write_scheme(build_dir() / "scheme.json", records, labels)
    hits = sum(1 for record in records if record.role == "entry" and not record.is_cross_listing)
    print(f"merged: {count} records, {hits} search hits → {destination}")
    print(f"report: {build_dir() / 'ingest_report.md'}")
    for warning in heading_warnings(records):
        print(f"warning: {warning}")
