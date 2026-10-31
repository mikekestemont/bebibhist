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
.venv/bin/pytest
```

`requirements.lock` is compiled from `pyproject.toml` with every extra (`dev`, `classify`, `embed`, `lock`). After changing a dependency, run `.venv/bin/pip-compile --extra dev --extra classify --extra embed --extra lock --strip-extras --allow-unsafe -o requirements.lock pyproject.toml`, then `.venv/bin/pip-sync requirements.lock` and `.venv/bin/pip install --no-deps -e .`. CI installs the `dev` extra with the lock file as constraints.

`bhb build` is the same sequence as `bhb ingest straive`, `bhb ingest pdfvol`, `bhb ingest vsmart` and `bhb merge`. `bhb export mods` writes that record as MODS 3.8, one file per BGB year, under `build/mods/`. `bhb export skos` writes the BHB scheme, the periods and the subject areas as SKOS to `build/skos/bhb.ttl`, from `data/curated/scheme.csv`, `theme_map.csv` and `facets.csv`. Derived files go to `build/` (git-ignored).

Raw inputs are not in this repository. Set `BHB_RAW` to the folder that holds them, or place that folder at `../bebibhist-raw`. It contains `2023-12-29/`, `exports Rijksarchief/`, `data/raw/`, `data/interim/` and `legacy/`. A missing folder stops the ingest with one error that names `BHB_RAW`. 1964–1965 are read from `$BHB_RAW/data/interim/print-pdf/`. 2008 is rebuilt from `$BHB_RAW/data/raw/pdf/BGB_2008.pdf` when that file is present; the regenerated XML is written to `build/print-pdf/BGB_2008.xml`.

```bash
.venv/bin/bhb gold sample          # 300 print entries → data/curated/gold/sample.xlsx
.venv/bin/bhb gold score           # intern 1992 sheets, or data/curated/gold/gold.xlsx once it exists
.venv/bin/bhb release             # build/release/records.jsonl.gz and NOTES.md
```

A release is made from a full run: `bhb build`, then `bhb similar` (a build drops the neighbours), then `bhb facets apply` (suggested periods and subject areas, marked as suggested), then `bhb places apply` (the places of the printed indexes, 1993–2007, and for the other entries the Belgian places their title names, marked as suggested), then `bhb release`. `bhb release` does not publish anything. After it has run, this command creates the data release (replace `YYYY-MM-DD` with the build date printed in `NOTES.md`):

```bash
gh release create data-YYYY-MM-DD build/release/records.jsonl.gz build/release/NOTES.md --title "BHB-BGB data YYYY-MM-DD" --notes-file build/release/NOTES.md
```

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
