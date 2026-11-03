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

    language = sub.add_parser("language", help="language of publication from the title (needs the language extra)")
    language_sub = language.add_subparsers(dest="language_command", required=True)
    language_sub.add_parser("apply", help="write suggested languages into build/records.jsonl")
    language_sub.add_parser("sample", help="write a sample per decade to label by hand: data/curated/language/sample.csv")
    language_sub.add_parser("score", help="score the suggestions in build/records.jsonl against the labelled sample")

    identifiers = sub.add_parser("identifiers", help="DOIs from Crossref (docs/IDENTIFIER_PROPOSAL.md)")
    identifiers_sub = identifiers.add_subparsers(dest="identifiers_command", required=True)
    pilot = identifiers_sub.add_parser("pilot", help="match a sample of recent articles and chapters; write build/identifiers/pilot.csv")
    pilot.add_argument("--size", type=int, default=1000)
    pilot.add_argument("--seed", type=int, default=1)
    match = identifiers_sub.add_parser("match", help="match every article and chapter of one source; write build/identifiers/<source>.csv")
    match.add_argument("--source", default="vsmart", help="vsmart, print-straive or print-pdf")
    match.add_argument("--offline", action="store_true", help="use only the answers already in the cache")
    identifiers_sub.add_parser("apply", help="write the accepted DOI, ISBN and ISSN matches into build/records.jsonl")
    identifiers_sub.add_parser("ocr", help="list words and names that differ from the matched source: build/identifiers/ocr-proposals.csv")
    openlib = identifiers_sub.add_parser("openlibrary", help="ISBNs for books from 1970 on from Open Library; write build/identifiers/openlibrary.csv")
    openlib.add_argument("--limit", type=int, default=None, help="only N books, spread over the years, for a trial")
    openlib.add_argument("--hosts", action="store_true", help="the collected volumes of chapters instead: build/identifiers/openlibrary-hosts.csv")
    identifiers_sub.add_parser("kbr-harvest", help="harvest KBR's Belgian Bibliography (OAI-PMH) by date windows into build/external/kbr; resumable")
    kbr = identifiers_sub.add_parser("kbr", help="match books and volumes to the KBR harvest (build/identifiers/kbr.csv), then fetch their ermes records")
    kbr.add_argument("--offline", action="store_true", help="match only; fetch no ermes records")
    vabb = identifiers_sub.add_parser("vabb", help="match entries from 1999 on to the VABB-SHW open data in build/external; write build/identifiers/vabb.csv")
    vabb.add_argument("--limit", type=int, default=None, help="only the first N entries, for a trial")
    sample = identifiers_sub.add_parser("sample", help="match a sample of printed articles and chapters across the years, as an answer key")
    sample.add_argument("--size", type=int, default=3000)
    sample.add_argument("--seed", type=int, default=2)

    cands = sub.add_parser("candidates", help="publications the bibliography may lack, from other sources")
    cands_sub = cands.add_subparsers(dest="candidates_command", required=True)
    cvabb = cands_sub.add_parser("vabb", help="VABB-SHW candidates for 2018–2023: build/candidates/vabb.csv and vabb-pilot.md")
    cvabb.add_argument("--threshold", type=float, default=0.8)

    journals = sub.add_parser("journals", help="one name per journal (docs/JOURNAL_PROPOSAL.md)")
    journals_sub = journals.add_subparsers(dest="journals_command", required=True)
    journals_sub.add_parser("apply", help="resolve Ibid., write data/curated/journals.csv and the spelling map, give articles a journal id")

    citations = sub.add_parser("citations", help="the LLM clean-up pass over printed citations (OpenRouter)")
    citations_sub = citations.add_subparsers(dest="citations_command", required=True)
    cpilot = citations_sub.add_parser("pilot", help="score models and the parser against the DOI and gold answer keys, in batches")
    cpilot.add_argument("--model", action="append", required=True, help="an OpenRouter model id with a pinned version (repeatable)")
    cpilot.add_argument("--per-decade", type=int, default=30, help="batches with a keyed entry per decade, besides the gold sheets' batches")
    cpilot.add_argument("--single", action="store_true", help="also send every keyed entry alone, to compare with batches")
    cpilot.add_argument("--provider", help="one OpenRouter provider without fallbacks (deepinfra/fp8, mistral/eu); Mistral models go to mistral/eu by default")
    cpilot.add_argument("--reasoning", help="reasoning effort to ask for (none, minimal, low, …); the model's default if omitted")
    cpilot.add_argument("--xml", action="store_true", help="send the vendor's JATS mark-up of each STRAIVE entry instead of the plain text")
    cpilot.add_argument("--workers", type=int, default=8)
    cpilot.add_argument("--seed", type=int, default=3)
    ckey = citations_sub.add_parser("key", help="score the parser and prompt variants on the hand-checked key (data/curated/citations/key.csv)")
    ckey.add_argument("--model", action="append", required=True)
    ckey.add_argument("--variant", choices=["v3", "v4", "v4-draft"], default="v4",
                      help="v3: one answer with translations; v4: parsing only; v4-draft: v4 checking the parser's draft")
    ckey.add_argument("--batch-size", type=int, default=10)
    ckey.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ckey.add_argument("--reasoning")
    ckey.add_argument("--provider")
    ckey.add_argument("--workers", type=int, default=3)
    cocr = citations_sub.add_parser("ocr", help="compare STRAIVE with the Persée digitisation of 1960–69 and score the model's OCR fixes on it")
    cocr.add_argument("--model", default="mistralai/mistral-small-2603")
    cocr.add_argument("--batches", type=int, default=150)
    cocr.add_argument("--seed", type=int, default=5)
    cocr.add_argument("--workers", type=int, default=3)
    ctrans = citations_sub.add_parser("translate", help="translate a sample of titles into nl, fr and en, title only, for a hand check and a cost")
    ctrans.add_argument("--model", action="append", required=True)
    ctrans.add_argument("--per-language", type=int, default=50)
    ctrans.add_argument("--provider", help="one OpenRouter provider without fallbacks (deepinfra/fp8, mistral/eu); Mistral models go to mistral/eu by default")
    ctrans.add_argument("--reasoning")
    ctrans.add_argument("--workers", type=int, default=8)
    ctrans.add_argument("--seed", type=int, default=4)

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
    if args.command == "language":
        _language(args.language_command)
        return
    if args.command == "identifiers" and args.identifiers_command == "pilot":
        _identifiers_pilot(args.size, args.seed)
        return
    if args.command == "identifiers" and args.identifiers_command == "match":
        _identifiers_match(args.source, args.offline)
        return
    if args.command == "identifiers" and args.identifiers_command == "apply":
        from bhb.identifiers import apply_identifiers

        path = build_dir() / "records.jsonl"
        records = read_jsonl(path)
        counts = apply_identifiers(records, build_dir() / "identifiers", build_dir() / "cache" / "crossref")
        from bhb.identifiers import open_access

        counts.update(open_access(records, build_dir() / "cache" / "openalex"))
        from bhb.identifiers import orcids

        counts.update(orcids(records, build_dir() / "cache" / "openalex-authors"))
        from bhb.kbr import apply_kbr

        counts.update(apply_kbr(records, build_dir() / "identifiers", build_dir() / "cache" / "kbr-ermes"))
        write_jsonl(path, records)
        print(f"identifiers: {counts} → {path}")
        return
    if args.command == "identifiers" and args.identifiers_command == "ocr":
        import csv

        from bhb.identifiers import ocr_proposals

        rows = ocr_proposals(read_jsonl(build_dir() / "records.jsonl"), build_dir() / "identifiers", build_dir() / "cache" / "crossref")
        out = build_dir() / "identifiers" / "ocr-proposals.csv"
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, ["id", "field", "ours", "theirs", "source"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"{len(rows)} proposals ({sum(row['field'] == 'author' for row in rows)} author names) → {out}")
        return
    if args.command == "candidates" and args.candidates_command == "vabb":
        _candidates_vabb(args.threshold)
        return
    if args.command == "identifiers" and args.identifiers_command == "kbr-harvest":
        from bhb.identifiers import USER_AGENT
        from bhb.kbr_harvest import fetcher, harvest

        fetched = harvest(build_dir() / "external" / "kbr", fetcher(USER_AGENT))
        print(f"kbr: {fetched} pages fetched now → {build_dir() / 'external' / 'kbr'}")
        return
    if args.command == "identifiers" and args.identifiers_command == "kbr":
        _identifiers_kbr(args.offline)
        return
    if args.command == "identifiers" and args.identifiers_command == "openlibrary":
        _identifiers_openlibrary_hosts() if args.hosts else _identifiers_openlibrary(args.limit)
        return
    if args.command == "identifiers" and args.identifiers_command == "vabb":
        _identifiers_vabb(args.limit)
        return
    if args.command == "identifiers" and args.identifiers_command == "sample":
        _identifiers_sample(args.size, args.seed)
        return
    if args.command == "journals" and args.journals_command == "apply":
        from bhb.journals import apply_journals

        path = build_dir() / "records.jsonl"
        records = read_jsonl(path)
        counts = apply_journals(records, repo_root() / "data" / "curated")
        write_jsonl(path, records)
        print(f"journals: {counts} → {path}")
        return
    if args.command == "citations" and args.citations_command == "pilot":
        _citations_pilot(args.model, args.per_decade, args.seed, args.single, args.reasoning, args.workers, args.provider, args.xml)
        return
    if args.command == "citations" and args.citations_command == "key":
        _citations_key(args.model, args.variant, args.batch_size, args.split, args.reasoning, args.workers, args.provider)
        return
    if args.command == "citations" and args.citations_command == "ocr":
        _citations_ocr(args.model, args.batches, args.seed, args.workers)
        return
    if args.command == "citations" and args.citations_command == "translate":
        _citations_translate(args.model, args.per_language, args.seed, args.reasoning, args.workers, args.provider)
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
    from bhb.ids import carry_former_ids, migrate_ids, previous_ids

    renumbered = carry_former_ids(merged, previous_ids(build_dir() / "records.jsonl"))
    print(f"ids: {len(renumbered)} entries changed id since the previous build; their former ids are kept")
    for name, count in migrate_ids(repo_root(), renumbered).items():
        print(f"ids: {count} ids moved to their new form in {name}")
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


def _language(command: str) -> None:
    import csv

    from bhb import language

    path = build_dir() / "records.jsonl"
    if not path.is_file():
        raise SystemExit("build/records.jsonl is missing; run bhb build first")
    records = read_jsonl(path)
    sheet = repo_root() / "data" / "curated" / "language" / "sample.csv"
    if command == "apply":
        counts = language.suggest(records)
        write_jsonl(path, records)
        print(f"language: {dict(sorted(counts.items(), key=lambda item: -item[1]))} → {path}")
    elif command == "sample":
        if sheet.exists():
            raise SystemExit(f"{sheet} exists and holds checked labels; move it away first")
        sheet.parent.mkdir(parents=True, exist_ok=True)
        rows = language.sample_rows(records)
        with sheet.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, language.SAMPLE_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"language: {len(rows)} entries to check → {sheet}")
    elif command == "score":
        with sheet.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        for period, scores in language.score_rows(records, rows).items():
            print(f"{period:>6}  checked {scores['checked']:>3}  coverage {scores['coverage']:.1%}  "
                  f"precision {scores['precision']:.1%}  first language right {scores['first language right']:.1%}")


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


def _identifiers_pilot(size: int, seed: int) -> None:
    from bhb.identifiers import pilot_sample

    records = read_jsonl(build_dir() / "records.jsonl")
    _identifiers_write(pilot_sample(records, size, seed), build_dir() / "identifiers" / "pilot.csv")


def _identifiers_match(source: str, offline: bool = False) -> None:
    records = read_jsonl(build_dir() / "records.jsonl")
    chosen = [record for record in records if record.source == source and record.role == "entry" and record.type in ("article", "chapter") and record.title]
    print(f"{len(chosen)} articles and chapters from {source}", flush=True)
    _identifiers_write(chosen, build_dir() / "identifiers" / f"{source}.csv", offline)


def _identifiers_vabb(limit: int | None) -> None:
    import csv
    from collections import Counter

    from bhb.vabb import Index, load, match

    index = Index(load(build_dir() / "external"))
    records = [record for record in read_jsonl(build_dir() / "records.jsonl")
               if record.role == "entry" and record.title and record.year and record.year >= 1999]
    records = records[:limit] if limit else records
    out = build_dir() / "identifiers" / "vabb.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[tuple[str, str, bool]] = Counter()
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "source", "type", "year", "host", "accepted", "vabb_id", "doi", "isbn", "issn", "title", "author",
                         "year_ok", "container", "page", "ours", "theirs", "their_container"])
        for number, record in enumerate(records, 1):
            found, pub = match(record, index)
            part = "catalogue" if record.source == "vsmart" else "print"
            counts[(part, record.type, found.accepted)] += 1
            writer.writerow([record.id, record.source, record.type, record.year, record.host.title if record.host else "", int(found.accepted),
                             pub.id if pub else "", (pub.doi or "") if pub else "", ";".join(pub.isbn) if pub else "", ";".join(pub.issn) if pub else "",
                             *(found.score.get(key, "") for key in ("title", "author", "year", "container", "page")),
                             found.our_title, found.their_title, found.their_container])
            if number % 10000 == 0:
                print(f"  {number}", flush=True)
    for (part, kind, accepted), n in sorted(counts.items()):
        print(f"{part:10} {kind:14} {'match' if accepted else 'none':5} {n}")
    print(f"vabb → {out}")


def _candidates_vabb(threshold: float) -> None:
    import csv
    from collections import Counter

    from bhb.vabb import load
    from bhb.vabb_candidates import CANDIDATE_YEARS, TEST_YEARS, TRAIN_YEARS, candidates, labels, train_and_measure

    pubs = load(build_dir() / "external")
    evaluation, model, _ = train_and_measure(pubs, labels(build_dir() / "identifiers" / "vabb.csv"))
    found = candidates(pubs, model, threshold)
    out = build_dir() / "candidates"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "vabb.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["vabb_id", "score", "year", "type", "authors", "title", "container", "disciplines", "language", "doi", "isbn", "issn"])
        for pub, score in found:
            writer.writerow([pub.id, f"{score:.3f}", pub.year, pub.type, "; ".join(pub.families or pub.editors), pub.title, pub.container,
                             "; ".join(pub.disciplines), pub.language, pub.doi or "", ";".join(pub.isbn), ";".join(pub.issn)])
    per_year = Counter(pub.year for pub, _ in found)
    lines = [
        "# VABB-SHW candidates: pilot", "",
        f"Trained on {TRAIN_YEARS.start}–{TRAIN_YEARS.stop - 1} ({evaluation.train} VABB publications, {evaluation.train_positive} in the "
        f"bibliography), measured on {TEST_YEARS.start}–{TEST_YEARS.stop - 1} ({evaluation.test}, {evaluation.test_positive} in the bibliography).",
        f"Average precision {evaluation.average_precision:.2f}. Precision is a lower bound: a publication the matcher missed, or one the",
        "bibliography should have taken, counts as a false positive.", "",
        "| Threshold | Precision | Recall | Proposed |", "|---|---:|---:|---:|",
        *[f"| {t:.2f} | {p:.2f} | {r:.2f} | {n} |" for t, p, r, n in evaluation.rows], "",
        f"Candidates for {CANDIDATE_YEARS.start}–{CANDIDATE_YEARS.stop - 1} at {threshold:.2f}: {len(found)} "
        f"({', '.join(f'{year}: {per_year[year]}' for year in sorted(per_year))}), in `vabb.csv`.",
    ]
    (out / "vabb-pilot.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def _identifiers_kbr(offline: bool) -> None:
    import json

    from bhb.kbr import books, ermes, match, name_index, write_matches

    records = read_jsonl(build_dir() / "records.jsonl")
    harvest = build_dir() / "external" / "kbr"
    matches, counts = match(records, books(harvest))
    out = build_dir() / "identifiers" / "kbr.csv"
    write_matches(out, matches)
    print(f"kbr: {counts} → {out}", flush=True)
    names = name_index(records, books(harvest))
    (build_dir() / "identifiers" / "kbr-names.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    print(f"kbr: {len(names)} family names of the bibliography in KBR → kbr-names.json", flush=True)
    if offline:
        return
    cache = build_dir() / "cache" / "kbr-ermes"
    missing = [found.number for found in matches if not (cache / f"{found.number}.xml.gz").exists()]
    print(f"kbr: fetching {len(missing)} ermes records (one a second)", flush=True)
    for number, kbr_number in enumerate(missing, 1):
        ermes(kbr_number, cache)
        if number % 250 == 0:
            print(f"  {number}", flush=True)


def _identifiers_openlibrary_hosts() -> None:
    import csv
    from collections import Counter

    from bhb.openlibrary import hosts, match

    volumes = hosts(read_jsonl(build_dir() / "records.jsonl"))
    print(f"{len(volumes)} collected volumes of chapters from 1970 on without an ISBN", flush=True)
    out = build_dir() / "identifiers" / "openlibrary-hosts.csv"
    counts: Counter[str] = Counter()
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["volume", "chapters", "accepted", "isbn", "work", "title", "author", "year", "editions", "ours", "theirs"])
        for number, (key, (volume, chapters)) in enumerate(sorted(volumes.items()), 1):
            found = match(volume, build_dir() / "cache" / "openlibrary")
            if found is None:
                counts["no candidate"] += 1
                continue
            counts["isbn" if found.accepted else "none"] += 1
            writer.writerow([key, ";".join(chapters), int(found.accepted), ";".join(found.isbn), found.work, found.title, found.author,
                             found.year, found.editions, found.ours, found.theirs])
            if number % 250 == 0:
                print(f"  {number}", flush=True)
    print(dict(counts), f"→ {out}")


def _identifiers_openlibrary(limit: int | None) -> None:
    import csv
    import random
    from collections import Counter

    from bhb.openlibrary import books, match

    chosen = books(read_jsonl(build_dir() / "records.jsonl"))
    if limit:
        chosen = random.Random(4).sample(chosen, min(limit, len(chosen)))
    print(f"{len(chosen)} books from 1970 on without an ISBN", flush=True)
    out = build_dir() / "identifiers" / ("openlibrary-trial.csv" if limit else "openlibrary.csv")
    counts: Counter[str] = Counter()
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "accepted", "isbn", "work", "title", "author", "year", "editions", "ours", "theirs"])
        for number, record in enumerate(chosen, 1):
            found = match(record, build_dir() / "cache" / "openlibrary")
            if found is None:
                counts["no candidate"] += 1
                continue
            counts["isbn" if found.accepted else "none"] += 1
            writer.writerow([found.record_id, int(found.accepted), ";".join(found.isbn), found.work, found.title, found.author,
                             found.year, found.editions, found.ours, found.theirs])
            if number % 500 == 0:
                print(f"  {number}", flush=True)
    print(dict(counts), f"→ {out}")


def _identifiers_sample(size: int, seed: int) -> None:
    """Printed articles and chapters, the same number from each decade, for an answer key of the OCR years."""
    import random
    from collections import defaultdict

    records = read_jsonl(build_dir() / "records.jsonl")
    by_decade = defaultdict(list)
    for record in records:
        if record.source.startswith("print") and record.role == "entry" and record.type in ("article", "chapter") and record.title and record.year:
            by_decade[record.bgb_year // 10 * 10].append(record)
    rng = random.Random(seed)
    share = size // len(by_decade)
    chosen = [record for decade in sorted(by_decade) for record in rng.sample(by_decade[decade], min(share, len(by_decade[decade])))]
    print(f"{len(chosen)} printed articles and chapters, {share} per decade", flush=True)
    _identifiers_write(chosen, build_dir() / "identifiers" / "print-sample.csv")


def _citations_keys(records: dict) -> tuple[dict, dict]:
    """The pilot's answer keys: per id the fields a Crossref DOI fixes, and the interns' corrected rows."""
    import csv

    from bhb.citations import key_from_crossref
    from bhb.identifiers import candidates

    cache = build_dir() / "cache" / "crossref"
    keys: dict[str, dict] = {}
    for name in ("print-sample.csv", "pilot.csv", "print-pdf.csv", "print-straive.csv"):
        path = build_dir() / "identifiers" / name
        if not path.exists():
            continue
        for row in csv.DictReader(path.open(encoding="utf-8")):
            record = records.get(row["id"])
            if row["accepted"] != "1" or record is None or not record.printed or record.id in keys:
                continue
            found = candidates(record, cache, offline=True)
            item = next((i for i in (found or {}).get("message", {}).get("items", []) if i.get("DOI") == row["doi"]), None)
            if item is not None:
                keys[record.id] = key_from_crossref(item)
    index = {(record.bgb_year, record.print_number): record.id for record in records.values() if record.print_number}
    gold = {index[(row.bgb_year, row.label)]: row for row in load_gold() if (row.bgb_year, row.label) in index}
    return keys, gold


def _citations_pass_size(records: list) -> tuple[int, int]:
    """Entries the full pass parses (printed, without a DOI or VABB match, or a collected volume) and titles it
    translates title only (every other entry)."""
    from bhb.citations import is_collected_volume

    parsed = sum(1 for record in records if record.source.startswith("print") and record.printed and (
        not (record.doi or "vabb" in record.identifiers_from.values()) or is_collected_volume(record.printed)))
    titled = sum(1 for record in records if record.title) - parsed
    return parsed, titled


def _citations_pilot(models: list[str], per_decade: int, seed: int, single: bool, reasoning: str | None, workers: int,
                     provider: str | None = None, xml: bool = False) -> None:
    import csv
    import random
    import time
    from collections import Counter, defaultdict
    from concurrent.futures import ThreadPoolExecutor

    from bhb.textutil import fold
    from bhb.citations import (PROMPT_VERSION, Batch, Item, ask_batch, combined, copied_values, expansion_right, fields_of_answer,
                               fields_of_record, make_batches, markup_of, tidy,
                               missing_translations, provider_for, score, score_gold)

    all_records = read_jsonl(build_dir() / "records.jsonl")
    records = {record.id: record for record in all_records}
    keys, gold = _citations_keys(records)
    journals = {row["id"]: row["title"] for row in csv.DictReader((repo_root() / "data" / "curated" / "journals.csv").open(encoding="utf-8"))}
    batches = make_batches([record for record in all_records if record.source.startswith("print")], journals)
    by_decade: dict[int, list] = defaultdict(list)
    for batch in batches:
        if any(item.id in keys or item.id in gold for item in batch.items):
            by_decade[records[batch.items[0].id].bgb_year // 10 * 10].append(batch)
    rng = random.Random(seed)
    chosen = []
    for decade in sorted(by_decade):
        with_gold = [batch for batch in by_decade[decade] if any(item.id in gold for item in batch.items)]
        rest = [batch for batch in by_decade[decade] if batch not in with_gold]
        chosen += with_gold + rng.sample(rest, min(per_decade, len(rest)))
    if xml:
        marked = markup_of([records[item.id] for batch in chosen for item in batch.items])
        chosen = [Batch(batch.section, batch.before, [Item(item.id, marked.get(item.id, item.printed), item.hints) for item in batch.items],
                        any(item.id in marked for item in batch.items)) for batch in chosen]
    sent = sum(len(batch.items) for batch in chosen)
    examples = {"bhb:1956-7739", "bhb:1977-29963"}  # the prompt's worked examples are not scored
    scored = [item.id for batch in chosen for item in batch.items if (item.id in keys or item.id in gold) and item.id not in examples]
    parsed, titled = _citations_pass_size(all_records)
    print(f"answer keys: {len(keys)} DOI entries, {len(gold)} gold rows; pilot: {len(chosen)} batches, {sent} entries, "
          f"{len(scored)} scored; the full pass parses {parsed} entries and translates {titled} titles alone", flush=True)

    def tally(fields_by_id: dict) -> Counter:
        counts: Counter = Counter()
        for record_id in scored:
            fields = fields_by_id.get(record_id)
            if fields is None:
                continue
            for name, ok in (score(fields, keys[record_id]) if record_id in keys else score_gold(fields, gold[record_id])).items():
                if ok is not None:
                    counts[(("doi" if record_id in keys else "gold"), name, ok)] += 1
        return counts

    parser_tally = tally({record_id: fields_of_record(records[record_id]) for record_id in scored})
    out = build_dir() / "citations"
    out.mkdir(parents=True, exist_ok=True)
    cache = build_dir() / "cache" / "citations"
    summary = []
    for model in models:
        slug = model.replace("/", "_") + f"-v{PROMPT_VERSION}" + (f"-r{reasoning}" if reasoning else "") + ("-xml" if xml else "")
        started = time.monotonic()
        with ThreadPoolExecutor(workers) as pool:
            results = list(pool.map(lambda batch: ask_batch(batch, model, cache, reasoning, provider), chosen))
        wall = time.monotonic() - started
        answers = {record_id: tidy(answer) for found, _ in results for record_id, answer in found.items()}
        replies = [reply for _, more in results for reply in more]
        errors = Counter(reply.error.split(":")[0] for reply in replies if reply.error)
        cost = sum(reply.cost for reply in replies)
        batch_tally = tally({record_id: fields_of_answer(answer) for record_id, answer in answers.items()})
        both_tally = tally({record_id: combined(fields_of_answer(answer), fields_of_record(records[record_id])) for record_id, answer in answers.items()})
        single_tally, single_cost, single_entries = Counter(), 0.0, 0
        if single:
            jobs = []
            for batch in chosen:
                before = batch.before
                for item in batch.items:
                    if item.id in keys or item.id in gold:
                        jobs.append(Batch(batch.section, before, [item], batch.markup))
                    before = item.printed
            with ThreadPoolExecutor(workers) as pool:
                alone = list(pool.map(lambda batch: ask_batch(batch, model, cache, reasoning, provider), jobs))
            single_tally = tally({record_id: fields_of_answer(answer) for found, _ in alone for record_id, answer in found.items()})
            single_cost = sum(reply.cost for _, more in alone for reply in more)
            single_entries = len(jobs)
        per_entry = cost / max(1, len(answers))
        disagree = {"type": 0, "language": 0}
        copied, values, untranslated, ocr = 0, 0, 0, 0
        expanded = Counter()
        by_full = {fold(title): journal_id for journal_id, title in journals.items()}
        with (out / f"answers-{slug}.jsonl").open("w", encoding="utf-8") as handle:
            for record_id, answer in answers.items():
                record = records[record_id]
                found, total = copied_values(answer, record.printed)
                copied, values = copied + found, values + total
                untranslated += missing_translations(answer)
                ocr += len(answer.get("ocr_fixes") or [])
                full = (answer.get("host") or {}).get("title_full")
                if record.type == "article" and record.journal_id in journals:
                    expanded["known"] += 1
                    expanded["known, written out"] += bool(full)
                    expanded["known, right"] += bool(full) and expansion_right(answer, journals[record.journal_id])
                elif record.type == "article" and not record.journal_id:
                    expanded["no journal id"] += 1
                    expanded["no journal id, written out"] += bool(full)
                    expanded["no journal id, a known journal"] += bool(full) and fold(full) in by_full
                disagree["type"] += answer.get("type") != record.type
                if record.language_suggested and answer.get("language") is not None:
                    disagree["language"] += sorted(answer["language"]) != sorted(record.language_suggested)
                handle.write(json.dumps({"id": record_id, "printed": record.printed, "answer": answer}, ensure_ascii=False) + "\n")
        lines = [f"# Citation pilot: {model}{' (vendor mark-up)' if xml else ''}", "",
                 f"{len(chosen)} batches, {len(answers)} of {sent} entries answered; {len(scored)} scored "
                 f"({sum(1 for i in scored if i in keys)} on a DOI, {sum(1 for i in scored if i in gold)} on the gold sheets).",
                 f"Reasoning: {reasoning or 'model default'}. Routing: {provider_for(model, provider)}. Providers: {dict(Counter(r.provider for r in replies if not r.cached))}.",
                 f"Requests: {len(replies)} ({len(replies) - len(chosen)} to redo a batch entry by entry); errors: {dict(errors)}.",
                 f"Cost: ${cost:.4f}, ${per_entry * 1000:.3f} per 1,000 entries; tokens per entry: "
                 f"{sum(r.tokens_in for r in replies) / max(1, len(answers)):.0f} in, {sum(r.tokens_out for r in replies) / max(1, len(answers)):.0f} out "
                 f"({sum(r.tokens_reasoning for r in replies) / max(1, len(answers)):.0f} of them reasoning).",
                 f"Time: {wall:.0f} s for the batches with {workers} at a time; median request "
                 f"{sorted(r.seconds for r in replies)[len(replies) // 2]:.1f} s.",
                 f"Full pass, {parsed:,} entries: about ${per_entry * parsed:,.0f}.",
                 f"Model and parser disagree on the type of {disagree['type']} entries and the local language on {disagree['language']}.",
                 f"Copied values found in the printed text: {copied / max(1, values):.1%} of {values}; translations missing: "
                 f"{untranslated} ({untranslated / max(1, len(answers)):.2f} per entry); OCR fixes proposed: {ocr}.",
                 f"Journal names written out: {expanded['known, written out']} of {expanded['known']} articles of a known journal, "
                 f"{expanded['known, right']} of them the curated name; {expanded['no journal id, written out']} of "
                 f"{expanded['no journal id']} articles without a journal id, {expanded['no journal id, a known journal']} of them a known journal's name.",
                 "", "| Key | Field | Parser | Model, batches | Model + parser | Model, single | Checked |", "|---|---|---:|---:|---:|---:|---:|"]
        rates = {}
        for key_name in ("doi", "gold"):
            for field_name in ("title", "authors", "host", "volume", "issue", "first_page", "year", "book"):
                checked = parser_tally[(key_name, field_name, True)] + parser_tally[(key_name, field_name, False)]
                if not checked:
                    continue
                cells = []
                for counts in (parser_tally, batch_tally, both_tally, single_tally):
                    right, wrong = counts[(key_name, field_name, True)], counts[(key_name, field_name, False)]
                    cells.append(f"{right / (right + wrong):.1%}" if right + wrong else "—")
                rates[(key_name, field_name)] = cells
                lines.append(f"| {key_name} | {field_name} | {' | '.join(cells)} | {checked} |")
        if single:
            lines.append(f"\nSingle entries: {single_entries} requests, ${single_cost:.4f}, "
                         f"${single_cost / max(1, single_entries) * 1000:.3f} per 1,000 entries.")
        (out / f"pilot-{slug}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines), flush=True)
        with (out / f"pilot-{slug}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "key", "field", "parser", "model", "printed"])
            for record_id in scored:
                if record_id not in answers:
                    writer.writerow([record_id, "", "unanswered", "", "", records[record_id].printed])
                    continue
                ours = score(fields_of_record(records[record_id]), keys[record_id]) if record_id in keys else score_gold(fields_of_record(records[record_id]), gold[record_id])
                theirs = score(fields_of_answer(answers[record_id]), keys[record_id]) if record_id in keys else score_gold(fields_of_answer(answers[record_id]), gold[record_id])
                for field_name in ours:
                    if ours[field_name] != theirs[field_name]:
                        writer.writerow([record_id, "doi" if record_id in keys else "gold", field_name, ours[field_name], theirs[field_name], records[record_id].printed])
        total = sum(batch_tally[k] for k in batch_tally if k[2] and k[0] == "doi")
        both = sum(both_tally[k] for k in both_tally if k[2] and k[0] == "doi")
        doi_checked = max(1, sum(n for k, n in batch_tally.items() if k[0] == "doi"))
        summary.append((model + (f", reasoning {reasoning}" if reasoning else "") + (", mark-up" if xml else ""), total / doi_checked, both / max(1, sum(n for k, n in both_tally.items() if k[0] == "doi")), copied / max(1, values), untranslated / max(1, len(answers)),
                        len(answers) / sent, per_entry * 1000, per_entry * parsed, wall))
    lines = ["| Model | DOI fields right | With the parser's where none | Copied as printed | Translations missing per entry | Answered | $ per 1,000 entries | Full pass | Batch time |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    parser_doi = sum(n for k, n in parser_tally.items() if k[2] and k[0] == "doi") / max(1, sum(n for k, n in parser_tally.items() if k[0] == "doi"))
    lines.append(f"| parser | {parser_doi:.1%} | | | | | | | |")
    for model, right, both, verbatim, untranslated, answered, per_thousand, full, wall in summary:
        lines.append(f"| {model} | {right:.1%} | {both:.1%} | {verbatim:.1%} | {untranslated:.2f} | {answered:.1%} | {per_thousand:.3f} | ${full:,.0f} | {wall:.0f} s |")
    print("\n".join(lines))
    with (out / "pilot-summary.md").open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {date.today()} — reasoning {reasoning or 'default'}, {len(chosen)} batches, seed {seed}\n\n" + "\n".join(lines) + "\n")


def _citations_key(models: list[str], variant: str, batch_size: int, split: str, reasoning: str | None, workers: int,
                   provider: str | None) -> None:
    import csv
    import time
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor

    from bhb.citations import (Item, answer_of_record, ask_batch, ask_parse, checked_ocr_fixes, copied_values, draft_hint,
                               load_key, make_batches, score_key, tidy)

    all_records = read_jsonl(build_dir() / "records.jsonl")
    records = {record.id: record for record in all_records}
    key = load_key(repo_root() / "data" / "curated" / "citations" / "key.csv")
    wanted = {record_id for record_id, row in key.items() if split == "all" or row["split"] == split}
    journals = {row["id"]: row["title"] for row in csv.DictReader((repo_root() / "data" / "curated" / "journals.csv").open(encoding="utf-8"))}
    batches = make_batches([record for record in all_records if record.source.startswith("print")], journals, size=batch_size)
    chosen = [batch for batch in batches if any(item.id in wanted for item in batch.items)]
    if variant == "v4-draft":
        for batch in chosen:
            batch.items = [Item(item.id, item.printed, item.hints + [draft_hint(records[item.id])]) for item in batch.items]
    sent = sum(len(batch.items) for batch in chosen)
    parsed, _ = _citations_pass_size(all_records)

    def tally(answers: dict) -> Counter:
        counts: Counter = Counter()
        for record_id in wanted:
            if record_id in answers:
                for name, ok in score_key(answers[record_id], key[record_id]).items():
                    if ok is not None:
                        counts[(name, ok)] += 1
        return counts

    def merged(model: dict, parser: dict) -> dict:
        """The model's fields, with the parser's year where the model gives none: filling other fields from the parser
        brings its errors back (a book's imprint as host)."""
        return dict(model, year=model.get("year") or parser.get("year"))

    parser_answers = {record_id: answer_of_record(records[record_id]) for record_id in wanted}
    parser_tally = tally(parser_answers)
    names = [name for name in ("type", "authors", "editors", "title", "title_translated", "host", "volume", "issue", "first_page",
                               "year", "place", "publisher", "extent", "series", "series_number") if parser_tally[(name, True)] + parser_tally[(name, False)]]
    out = build_dir() / "citations"
    cache = build_dir() / "cache" / "citations"
    rate = lambda counts, name: (lambda r, w: f"{r / (r + w):.1%}" if r + w else "—")(counts[(name, True)], counts[(name, False)])
    overall = lambda counts: sum(n for (name, ok), n in counts.items() if ok) / max(1, sum(counts.values()))
    rows = []
    for model in models:
        label = f"{model.split('/')[-1]} {variant} b{batch_size}" + (f" r-{reasoning}" if reasoning else "")
        ask = (lambda batch: ask_batch(batch, model, cache, reasoning, provider)) if variant == "v3" else \
              (lambda batch: ask_parse(batch, model, cache, reasoning, provider, draft=variant == "v4-draft"))
        started = time.monotonic()
        with ThreadPoolExecutor(workers) as pool:
            results = list(pool.map(ask, chosen))
        wall = time.monotonic() - started
        answers = {record_id: tidy(answer, records[record_id].printed, records[record_id].bgb_year)
                   for found, _ in results for record_id, answer in found.items()}
        replies = [reply for _, more in results for reply in more]
        cost = sum(reply.cost for reply in replies)
        model_tally = tally(answers)
        with (out / f"key-{split}-{label.replace(' ', '-')}.jsonl").open("w", encoding="utf-8") as handle:
            for record_id in sorted(wanted & set(answers)):
                handle.write(json.dumps({"id": record_id, "score": score_key(answers[record_id], key[record_id]),
                                         "answer": answers[record_id], "parser": parser_answers[record_id]}, ensure_ascii=False) + "\n")
        both_tally = tally({record_id: merged(answers[record_id], parser_answers[record_id]) for record_id in wanted if record_id in answers})
        invented = sum(1 for record_id, answer in answers.items() if (lambda f: f[0] < f[1])(copied_values(answer, records[record_id].printed)))
        proposed = sum(len(answer.get("ocr_fixes") or []) for answer in answers.values())
        kept = sum(len(checked_ocr_fixes(answer, records[record_id].printed)) for record_id, answer in answers.items())
        per_entry = cost / max(1, len(answers))
        rows.append((label, model_tally, both_tally, len([i for i in wanted if i in answers]), len(answers) / sent, invented / max(1, len(answers)),
                     proposed, kept, per_entry, wall, Counter(r.error.split(":")[0] for r in replies if r.error)))
        print(f"{label}: {len(answers)} of {sent} answered, ${cost:.4f}, {wall:.0f} s", flush=True)
    lines = [f"# Hand-checked key, {split} ({len(wanted)} entries), {date.today()}", "",
             "| Field | Parser | " + " | ".join(f"{row[0]} | + parser's year" for row in rows) + " |",
             "|---|---:|" + "---:|---:|" * len(rows)]
    for name in names:
        lines.append(f"| {name} | {rate(parser_tally, name)} | " + " | ".join(f"{rate(row[1], name)} | {rate(row[2], name)}" for row in rows) + " |")
    lines.append(f"| **all fields** | **{overall(parser_tally):.1%}** | " + " | ".join(f"**{overall(row[1]):.1%}** | **{overall(row[2]):.1%}**" for row in rows) + " |")
    lines += ["", "| Variant | Key entries answered | All answered | Entries with a value not in the text | OCR fixes proposed / kept by the rule | $ per 1,000 | Full pass | Time | Errors |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for label, _, _, scored, answered, invented, proposed, kept, per_entry, wall, errors in rows:
        lines.append(f"| {label} | {scored} | {answered:.1%} | {invented:.1%} | {proposed} / {kept} | {per_entry * 1000:.3f} | ${per_entry * parsed:,.0f} | {wall:.0f} s | {dict(errors)} |")
    text = "\n".join(lines) + "\n"
    print(text)
    with (out / "key-summary.md").open("a", encoding="utf-8") as handle:
        handle.write("\n" + text)


def _citations_ocr(model: str, size: int, seed: int, workers: int) -> None:
    """The model's OCR fixes against a second digitisation: STRAIVE and Persée read 1960–63 and 1966–69 apart."""
    import csv
    import random
    from collections import Counter, defaultdict
    from concurrent.futures import ThreadPoolExecutor

    from bhb.citations import ask_parse, checked_ocr_fixes, make_batches
    from bhb.ocr_compare import compare, key, persee_entries, vocabulary, words

    all_records = read_jsonl(build_dir() / "records.jsonl")
    records = {record.id: record for record in all_records}
    persee_dir = build_dir() / "persee"
    counts = vocabulary(record.printed for record in all_records)
    found, tally = compare(all_records, persee_dir, counts)
    out = build_dir() / "citations"
    with (out / "persee-differences.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "straive", "persee", "verdict", "pdf_page"])
        for difference in found:
            writer.writerow([difference.record_id, difference.straive, difference.persee, difference.verdict, difference.page])
    by_entry: dict[str, list] = defaultdict(list)
    for difference in found:
        by_entry[difference.record_id].append(difference)
    persee = {}
    for year in (1960, 1961, 1962, 1963, 1966, 1967, 1968, 1969):
        for number, (text, page) in persee_entries(persee_dir / f"BGB_{year}.xml").items():
            persee[(year, number)] = (text, page)
    paired = {record.id for record in all_records if record.source == "print-straive" and (record.bgb_year, record.print_number) in persee}
    journals = {row["id"]: row["title"] for row in csv.DictReader((repo_root() / "data" / "curated" / "journals.csv").open(encoding="utf-8"))}
    batches = [batch for batch in make_batches([r for r in all_records if r.source.startswith("print")], journals)
               if all(item.id in paired for item in batch.items)]
    chosen = random.Random(seed).sample(batches, min(size, len(batches)))
    cache = build_dir() / "cache" / "citations"
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda batch: ask_parse(batch, model, cache), chosen))
    answers = {record_id: answer for found_, _ in results for record_id, answer in found_.items()}
    cost = sum(reply.cost for _, replies in results for reply in replies)
    verdicts = {"proposed": Counter(), "kept by the rule": Counter()}
    examples = []
    for record_id, answer in answers.items():
        record = records[record_id]
        text, page = persee[(record.bgb_year, record.print_number)]
        other = {key(word) for word in words(text)}
        differences = by_entry.get(record_id, [])
        kept = checked_ocr_fixes(answer, record.printed, counts)
        for fix in answer.get("ocr_fixes") or []:
            wrong, right = key(fix.get("printed") or ""), key(fix.get("corrected") or "")
            if any(wrong and wrong in key(d.straive) and right and key(d.persee).find(right) >= 0 for d in differences):
                verdict = "confirmed by Persée"
            elif wrong and wrong in other:
                verdict = "contradicted: Persée reads the same"
            else:
                verdict = "unresolved"
            verdicts["proposed"][verdict] += 1
            if fix in kept:
                verdicts["kept by the rule"][verdict] += 1
            examples.append([record_id, fix.get("printed"), fix.get("corrected"), verdict, fix in kept, page])
    errors = [d for record_id in answers for d in by_entry.get(record_id, []) if d.verdict == "persee"]
    caught = sum(1 for d in errors if any(key(fix.get("printed") or "") and key(fix.get("printed") or "") in key(d.straive)
                                          for fix in answers[d.record_id].get("ocr_fixes") or []))
    with (out / "persee-ocr-fixes.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "printed", "corrected", "verdict", "kept_by_rule", "pdf_page"])
        writer.writerows(examples)
    lines = [f"# STRAIVE and Persée, 1960–63 and 1966–69 ({date.today()})", "",
             f"Entries paired by print number: {tally['paired']:,} ({tally['words']:,} words); not in Persée {tally['not in Persée']}, "
             f"too far apart to compare {tally['too far apart']}.",
             f"Words read differently: {tally['persee'] + tally['straive'] + tally['undecided']:,}. Decided by the word list for "
             f"Persée (an OCR error in STRAIVE) {tally['persee']}, for STRAIVE {tally['straive']}, undecided {tally['undecided']:,}.",
             f"All differences: {out / 'persee-differences.csv'}.", "",
             f"## The model's OCR fixes ({model}, prompt v4, {len(chosen)} batches, {len(answers)} entries, ${cost:.3f})", "",
             "| Fix | Proposed | Kept by the rule (with word counts) |", "|---|---:|---:|"]
    for verdict in ("confirmed by Persée", "contradicted: Persée reads the same", "unresolved"):
        lines.append(f"| {verdict} | {verdicts['proposed'][verdict]} | {verdicts['kept by the rule'][verdict]} |")
    lines += ["", f"STRAIVE errors in these entries that the word list decides for Persée: {len(errors)}; the model proposed a fix for {caught}.",
              f"Fixes: {out / 'persee-ocr-fixes.csv'}."]
    text = "\n".join(lines) + "\n"
    (out / "persee-ocr.md").write_text(text, encoding="utf-8")
    print(text)


def _citations_translate(models: list[str], per_language: int, seed: int, reasoning: str | None, workers: int,
                         provider: str | None = None) -> None:
    import csv
    import random
    import re
    import time
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor

    from bhb.citations import Item, ask_titles

    all_records = read_jsonl(build_dir() / "records.jsonl")
    rng = random.Random(seed)
    terms = re.compile(r"costume|coutum|échevin|schepen|mainmorte|dode hand|keure|leenhof|cijns|tonlieu|baljuw|bailli|ambacht|métier|gilde|heerlijkheid|seigneurie", re.IGNORECASE)
    # The plan's check (§5c): 50 titles per language pair, historical terms among them. Titles in one language only,
    # so that every translation has one source.
    by_language: dict[str, list] = {}
    for record in all_records:
        if record.title and len(record.language_suggested) == 1:
            language = record.language_suggested[0] if record.language_suggested[0] in ("nl", "fr", "en", "de") else "other"
            by_language.setdefault(language, []).append(record)
    sizes = {"nl": per_language, "fr": per_language, "en": per_language // 2, "de": per_language // 2, "other": per_language // 5}
    chosen = [record for language in sizes for record in rng.sample(by_language[language], sizes[language])]
    seen = {record.id for record in chosen}
    chosen += rng.sample([record for language in ("nl", "fr") for record in by_language[language]
                          if record.id not in seen and terms.search(record.title)], per_language)
    items = [Item(record.id, ": ".join(part for part in (record.title, record.subtitle) if part)
                  + (f" [{record.title_translated}]" if record.title_translated else ""), list(record.language_suggested)) for record in chosen]
    groups = [items[start:start + 25] for start in range(0, len(items), 25)]
    parsed, titled = _citations_pass_size(all_records)
    out = build_dir() / "citations"
    out.mkdir(parents=True, exist_ok=True)
    cache = build_dir() / "cache" / "citations"
    for model in models:
        slug = model.replace("/", "_")
        started = time.monotonic()
        with ThreadPoolExecutor(workers) as pool:
            results = list(pool.map(lambda group: ask_titles(group, model, cache, reasoning, provider), groups))
        found = {record_id: title for answers, _ in results for record_id, title in answers.items()}
        replies = [reply for _, reply in results]
        # A title whose batch failed, or that lacks a translation it needs, is asked again alone.
        needs = lambda item: [code for code in ("nl", "fr", "en") if code not in item.hints and not (found.get(item.id) or {}).get(code)]
        again = [item for item in items if needs(item)]
        with ThreadPoolExecutor(workers) as pool:
            alone = list(pool.map(lambda item: ask_titles([item], model, cache, reasoning, provider), again))
        for answers, reply in alone:
            replies.append(reply)
            for record_id, title in answers.items():
                found[record_id] = {code: (found.get(record_id) or {}).get(code) or title.get(code) for code in ("nl", "fr", "en")}
        wall = time.monotonic() - started
        cost = sum(reply.cost for reply in replies)
        per_title = cost / max(1, len(found))
        missing = sum(len(needs(item)) for item in items)
        with (out / f"translate-{slug}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "language", "title", "editors_translation", "nl", "fr", "en"])
            for record, item in zip(chosen, items):
                answer = found.get(record.id) or {}
                writer.writerow([record.id, "+".join(record.language_suggested), ": ".join(part for part in (record.title, record.subtitle) if part),
                                 record.title_translated or "", answer.get("nl") or "", answer.get("fr") or "", answer.get("en") or ""])
        lines = [f"# Title translations: {model}", "",
                 f"{len(found)} of {len(items)} titles answered in {len(replies)} requests ({len(again)} asked again alone); "
                 f"errors: {dict(Counter(r.error.split(':')[0] for r in replies if r.error))}.",
                 f"Cost ${cost:.4f}, ${per_title * 1000:.3f} per 1,000 titles; tokens per title "
                 f"{sum(r.tokens_in for r in replies) / max(1, len(found)):.0f} in, {sum(r.tokens_out for r in replies) / max(1, len(found)):.0f} out "
                 f"({sum(r.tokens_reasoning for r in replies) / max(1, len(found)):.0f} reasoning); {wall:.0f} s.",
                 f"Translations still missing: {missing}.",
                 f"Every title of the bibliography ({parsed + titled:,}): about ${per_title * (parsed + titled):,.0f}.",
                 f"Sheet: {out / f'translate-{slug}.csv'}."]
        (out / f"translate-{slug}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines), flush=True)


def _identifiers_write(sample, out: Path, offline: bool = False) -> None:
    import csv
    from collections import Counter

    from bhb.identifiers import run

    by_id = {record.id: record for record in sample}
    matches = run(sample, build_dir() / "cache" / "crossref", progress=lambda n: print(f"  {n}", flush=True), offline=offline)
    out.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[tuple[str, str, bool]] = Counter()
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "source", "type", "year", "host", "accepted", "doi", "title", "author", "year_ok", "container", "page", "ours", "theirs", "their_container"])
        for match in matches:
            record = by_id[match.record_id]
            counts[(record.source, record.type, match.accepted)] += 1
            writer.writerow([match.record_id, record.source, record.type, record.year or "", record.host.title if record.host else "",
                             int(match.accepted), match.doi or "",
                             *(match.score.get(key, "") for key in ("title", "author", "year", "container", "page")),
                             match.our_title, match.their_title, match.their_container])
    for (source, kind, accepted), n in sorted(counts.items()):
        print(f"{source:14} {kind:8} {'DOI' if accepted else 'none':4} {n}")
    print(f"identifiers → {out}")
