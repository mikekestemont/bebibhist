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
from pathlib import Path

from bhb.bench import build_database, load_corpus, serve
from bhb.gold import format_score, load_gold, score_records, write_sample
from bhb.ingest.jats import load_jats, straive_paths
from bhb.ingest.pdf_volume import convert_pdf
from bhb.ingest.vsmart import load_vsmart
from bhb.io_utils import read_jsonl, write_jsonl
from bhb.merge import merge_records, write_report, write_scheme
from bhb.mods import export_mods
from bhb.model import Record
from bhb.paths import build_dir, repo_root


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
    sub.add_parser("build", help="ingest every source and merge")

    gold = sub.add_parser("gold", help="sample entries for correction, or score a corrected sheet")
    gold_sub = gold.add_subparsers(dest="gold_command", required=True)
    sample = gold_sub.add_parser("sample", help="write a stratified sample of print entries")
    sample.add_argument("--n", type=int, default=300)
    sample.add_argument("--seed", type=int, default=2026)
    sample.add_argument("--out", type=Path)
    score = gold_sub.add_parser("score", help="field accuracy against a corrected sheet")
    score.add_argument("--gold", type=Path, nargs="*", help="defaults to the intern 1992 sheets")

    bench = sub.add_parser("bench", help="synthetic search database for the browser benchmark")
    bench_sub = bench.add_subparsers(dest="bench_command", required=True)
    bench_build = bench_sub.add_parser("build", help="write build/bench from the merged records")
    bench_build.add_argument("--n", type=int, default=270_000)
    bench_build.add_argument("--seed", type=int, default=2026)
    bench_serve = bench_sub.add_parser("serve", help="serve the repo with HTTP range responses")
    bench_serve.add_argument("--port", type=int, default=8765)
    bench_serve.add_argument("--latency-ms", type=int, default=0, help="extra delay per range response")
    bench_serve.add_argument("--bytes-per-second", type=int, default=0, help="cap each range response")

    export = sub.add_parser("export", help="write the semantic record out for archive and exchange")
    export_sub = export.add_subparsers(dest="export_command", required=True)
    mods = export_sub.add_parser("mods", help="MODS 3.8, one collection per BGB year")
    mods.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    if args.command == "build":
        build()
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
    if args.command == "bench" and args.bench_command == "build":
        _bench_build(args.n, args.seed)
        return
    if args.command == "bench" and args.bench_command == "serve":
        serve(args.port, latency_ms=args.latency_ms, bytes_per_second=args.bytes_per_second)
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
    _emit(merged, labels, None)
    return merged


def ingest_straive() -> list[Record]:
    records: list[Record] = []
    for path in straive_paths(repo_root()):
        year_records = load_jats(path, "print-straive")
        print(f"  {path.name}: {len(year_records)}")
        records.extend(year_records)
    return records


def ingest_pdf(convert: bool = True) -> list[Record]:
    root = repo_root()
    interim = root / "data" / "interim" / "print-pdf"
    interim.mkdir(parents=True, exist_ok=True)
    pdf = root / "data" / "raw" / "pdf" / "BGB_2008.pdf"
    target = interim / "BGB_2008.xml"
    if convert and pdf.is_file():
        report = convert_pdf(pdf, target, "2008")
        print(f"  2008 PDF: {report['entries']} entries ({report['first']}–{report['last']})")
    elif not target.is_file():
        print("  2008 PDF not found and no BGB_2008.xml yet; that year is skipped")
    records: list[Record] = []
    for name in ("BGB_1964.xml", "BGB_1965.xml", "BGB_2008.xml"):
        path = interim / name
        if not path.is_file():
            print(f"  missing {path.name}")
            continue
        year_records = load_jats(path, "print-pdf")
        print(f"  {path.name}: {len(year_records)}")
        records.extend(year_records)
    return records


def ingest_vsmart_records() -> tuple[list[Record], dict]:
    directory = repo_root() / "exports Rijksarchief"
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


def _bench_build(n: int, seed: int) -> None:
    source = build_dir() / "records.jsonl"
    if not source.is_file():
        raise SystemExit("build/records.jsonl is missing; run bhb build first")
    folder = build_dir() / "bench"
    print(f"reading titles from {source}")
    summary = build_database(load_corpus(source), folder / "bhb.sqlite", n=n, seed=seed)
    print(
        f"bench: {summary['records']} records, {summary['histoire_hits']} hits for 'histoire', "
        f"{summary['bytes'] / 1_048_576:.0f} MB in {summary['chunks']} chunks → {folder}"
    )


def _load_built_records() -> list[Record]:
    path = build_dir() / "records.jsonl"
    if not path.is_file():
        raise SystemExit("build/records.jsonl is missing; run bhb build first")
    return read_jsonl(path)


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
