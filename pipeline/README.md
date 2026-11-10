# `bhb` pipeline

Python package that turns the raw sources of the Bibliography of Belgian History into one dataset.
See `../docs/PROTOTYPE_SPEC.md` for the overall design.

```bash
cd pipeline
python3.12 -m venv .venv                     # pinned in .python-version
.venv/bin/pip install -r requirements.lock   # exact versions, including the embed extra (torch, sentence-transformers)
.venv/bin/pip install --no-deps -e .
.venv/bin/bhb build          # straive + pdf years + V-Smart → build/records.jsonl
.venv/bin/bhb similar        # similar publications (bge-m3 + rare-word TF-IDF); vectors cached in build/vectors/
.venv/bin/bhb topicmap layout # the map of subjects: UMAP of the English translations, regions (needs the topicmap extra)
.venv/bin/bhb topicmap names  # names the regions with a local model (Mistral Small 3.2, mlx-lm): data/curated/topic_regions.json
.venv/bin/pytest
```

`requirements.lock` is compiled from `pyproject.toml` with every extra (`dev`, `classify`, `embed`, `lock`). After changing a dependency, run `.venv/bin/pip-compile --extra dev --extra classify --extra embed --extra lock --strip-extras --allow-unsafe -o requirements.lock pyproject.toml`, then `.venv/bin/pip-sync requirements.lock` and `.venv/bin/pip install --no-deps -e .`. CI installs the `dev` extra with the lock file as constraints.

`bhb build` is the same sequence as `bhb ingest straive`, `bhb ingest pdfvol`, `bhb ingest vsmart` and `bhb merge`. `bhb merge` first applies the hand corrections of `data/curated/corrections.csv`, then the machine-found OCR corrections of `data/curated/ocr_persee.csv` (written by `bhb corrections persee` from the STRAIVE–Persée comparison; then the names misread by OCR of `data/curated/ocr_names.csv` (written by `bhb corrections names` from the names' spellings and KBR's authors in `build/external/kbr/`; it keeps the rows a build has already applied; kind `name` corrects the people's names only, never the printed citation); `bhb corrections apply` applies the three files to an existing build) (columns `id`, `wrong`, `right`, `kind` = `ocr` or `print`, `checked_by`, `date`, `note`): an `ocr` row corrects the text everywhere in the entry, the printed citation included; a `print` row corrects the parsed fields and leaves the citation as printed. A row that no longer matches is reported on stderr. `bhb export mods` writes that record as MODS 3.8, one file per BGB year, under `build/mods/`. `bhb export skos` writes the BHB scheme, the periods and the subject areas as SKOS to `build/skos/bhb.ttl`, from `data/curated/scheme.csv`, `theme_map.csv` and `facets.csv`. Derived files go to `build/` (git-ignored).

Raw inputs are not in this repository. Set `BHB_RAW` to the folder that holds them, or place that folder at `../bebibhist-raw`. It contains `2023-12-29/`, `exports Rijksarchief/`, `data/raw/`, `data/interim/` and `legacy/`. A missing folder stops the ingest with one error that names `BHB_RAW`. 1964–1965 are read from `$BHB_RAW/data/interim/print-pdf/`. 2008 is rebuilt from `$BHB_RAW/data/raw/pdf/BGB_2008.pdf` when that file is present; the regenerated XML is written to `build/print-pdf/BGB_2008.xml`.

```bash
.venv/bin/bhb gold sample          # 300 print entries → data/curated/gold/sample.xlsx
.venv/bin/bhb gold score           # intern 1992 sheets, or data/curated/gold/gold.xlsx once it exists
.venv/bin/bhb release             # build/release/records.jsonl.gz and NOTES.md
```

A release is made from a full run: `bhb build`, then `bhb citations apply` (the fields of the citation pass, `build/citations/run/`, in place of the parser's, flagged `parsed-llm`, and every title's machine translations into nl, fr and en, for search only; the printed text stays; the correction files are applied again afterwards, since the model read the uncorrected text; then the split ligatures and lost line-break hyphens the model copied into the fields are repaired where the printed texts show the right form, `bhb/repair.py`, and a chapter linked to its volume through "Cfr. n°" takes the volume's parsed imprint and year), then `bhb similar` (a build drops the neighbours), then `bhb facets apply` (suggested periods and subject areas, marked as suggested), then `bhb places apply` (the places of the printed indexes, 1993–2007, and for the other entries the Belgian places their title names, marked as suggested), then `bhb identifiers apply` (DOIs, ISBNs and ISSNs from the Crossref and VABB-SHW matches in `build/identifiers/`, with journal names for articles whose journal record was not exported), then `bhb journals apply` ("Ibid." resolved, `data/curated/journals.csv`, a journal id per article; it runs once on a fresh build; it also links the same publication listed in two volumes of the Bibliography, `duplicate_of`, `bhb/duplicates.py`, so that the site shows it as one record), then `bhb language apply` (the language of publication read from the title or, for a title of names, its journal or volume, marked as suggested; needs the `language` extra; `bhb language score` checks it against `data/curated/language/sample.csv`), then `bhb topicmap apply` (each entry's place on the map of subjects and its finest region, from `build/topicmap/layout.npz`; `bhb topicmap layout` and `bhb topicmap names` make that file and `data/curated/topic_regions.json` again when the entries change much, about 5 minutes and an hour, the names cached in `build/topicmap/names-cache.jsonl`), then `bhb release`. The matches themselves come from `bhb identifiers match --source vsmart`, `--source print-straive` and `--source print-pdf` (add `--offline` to re-score from the cache after a rule change, without querying Crossref; after a fresh `bhb build`, run `bhb journals apply` first, since printed articles are looked for in their journal by its ISSN and a fresh build has no journal ids yet) and `bhb identifiers vabb` (with the VABB-SHW open data in `build/external/`); `bhb identifiers openlibrary` adds ISBNs for books from 1970 on (a work with one edition only); `bhb identifiers kbr-harvest` harvests KBR's Belgian Bibliography into `build/external/kbr/` by date windows (resumable, about a day; `bhb/kbr_harvest.py` also runs on its own, with Python 3.8 and no packages: `python3 kbr_harvest.py FOLDER`), and `bhb identifiers kbr` matches the books and collected volumes to it (`build/identifiers/kbr.csv`, `kbr-names.json`) and fetches each match's ermes record into `build/cache/kbr-ermes/` (`--offline` matches only); `bhb identifiers apply` then adds the KBR link, the ISBN and authors' given names written out; their Crossref answers are cached in `build/cache/crossref/`, so a rebuild does not query again. Set `BHB_CONTACT` to a contact address for Crossref's faster pool. `bhb release` does not publish anything. Before the release, run the deploy's search checks on the site built from these records, locally (`npm --prefix site run verify`: index, build, `vite preview`, `tests/search-checks.mjs`; about 15 minutes, or 3 with `-- --no-index` when the index is already built from them); a check whose count range the new data rightly leave is widened in the same commit. Then this command creates the data release (replace `YYYY-MM-DD` with the build date printed in `NOTES.md`):

```bash
gh release create data-YYYY-MM-DD build/release/records.jsonl.gz build/release/NOTES.md --title "BHB-BGB data YYYY-MM-DD" --notes-file build/release/NOTES.md
```

The citation clean-up pass (`bhb/citations.py`, plan §5c) is piloted before it runs in full; set `OPENROUTER_API_KEY` first. `bhb citations pilot --model ID [--model ID …]` sends batches of consecutive entries that hold an entry of the answer key (a Crossref DOI match, or a row of the interns' 1992 sheets), balanced by decade (`--per-decade`), scores the parser and each model per field, and estimates the cost of the full pass; `--single` also sends each keyed entry alone, `--reasoning low` asks for a reasoning effort. `bhb citations translate --model ID` translates a sample of titles per language, plus titles with historical terms, into a sheet for a hand check (`build/citations/translate-*.csv`). `bhb citations key --model ID --variant v4 --split dev` scores the parser and a prompt variant (`v3`, `v4`, `v4-draft`; `--batch-size`) on the hand-checked key `data/curated/citations/key.csv`; keep `--split test` for the final comparison. `bhb citations run` is the full pass: it parses the printed entries without a DOI or VABB match (and every collected volume) with prompt v4, then translates every title, the parsed ones from the model's title, for search only; answers, translations, a review list and a report go to `build/citations/run/` (`--years 1975` for a test run into `run-1975/`), and nothing in the records changes yet. It resumes from the cache and stops when the key runs out of credit. `bhb citations ocr` compares STRAIVE with the Persée digitisation of 1960–63 and 1966–69 (first convert each year with `python -m bhb.ingest.persee_pdf … --out build/persee/BGB_<year>.xml`), writes every word read differently with a verdict (`build/citations/persee-differences.csv`) and scores the model's OCR fixes on a sample. Answers are cached in `build/cache/citations/`, keyed on the whole request; reports go to `build/citations/`.

The search benchmark that chose Pagefind over browser SQLite is recorded in `docs/BENCHMARK.md`. The benchmark code itself has been removed.

## Modules

### `bhb.ingest.jats` — STRAIVE years and PDF years

Reads `BGB_YYYY.xml`. Vendor tags fill the record when they exist; a plain-text citation parser is used for PDF years (no inline tags). Section paths are rebuilt from heading numbers. Print numbers that fall outside their neighbours are repaired.

### `bhb.ingest.pdf_volume` — BGB 2008

Born-digital yearly PDF (no outline). Writes `build/print-pdf/BGB_2008.xml` in the same plain-text JATS shape as the Persée recovery. The PDF itself stays in the raw folder.

### `bhb.ingest.vsmart` — catalogue exports 2009–2017

### `bhb.ingest.persee_pdf` — print volumes from Persée PDFs

Rebuilds one BGB year from the decade PDFs on rbph-btfg.be into the same JATS-like structure as the
STRAIVE files (nested `<ref-list>` sections, one `<ref>` per printed entry), so that every year can
flow through the same downstream steps. Used for **1964 and 1965**, which STRAIVE did not deliver.

```bash
python -m bhb.ingest.persee_pdf "$BHB_RAW/data/raw/pdf/BGB_1960-69.pdf" 1964 \
    --headings-from "$BHB_RAW/2023-12-29/BGB_1960-69" \
    --out "$BHB_RAW/data/interim/print-pdf/BGB_1964.xml"
```

Writes `BGB_1964.xml` plus `BGB_1964.report.json` (counts, numbers absent from the print sequence,
heading tree, flagged entries).

What it does and does not do:
- Entries are segmented on the consecutive print numbers; OCR-garbled numbers (`6305` for 6385,
  `71 1 1`) and `bis` entries are handled and flagged in `content-type="check:…"`.
- Each `<ref>` records its PDF page and printed page (`specific-use="pdf-page:403 print-page:1378"`),
  so the website can link to the original page.
- `<mixed-citation>` holds the plain printed text (`publication-type="unknown"`); no inline mark-up.
  Field-level structuring happens in a later, shared step for all years.
- The section tree is best effort (outline + numbering + heading dictionary from neighbouring years)
  and needs an editorial check; known misses are listed below.

Results (2026-10-11):

| Year | Entries | Print numbers absent | Notes |
|---|---|---|---|
| 1964 | 1,218 (6347–7574, incl. 7053bis) | 11 | Heading "F.II Les églises" missed (its entries sit under F.I.c) |
| 1965 | 1,419 (7575–9003, incl. 8544bis) | 11 | Headings "F.III" and "F.IV" missed (their entries sit under F.II) |

The absent numbers do not occur anywhere in the text layer; the STRAIVE volumes of the same decade show
4–8 such gaps per year, so most are genuine gaps in the printed numbering.
