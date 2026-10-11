# `bhb` pipeline

Python package that turns the raw sources of the Bibliography of Belgian History into one dataset.
See `../PLAN.md` for the overall design.

```bash
cd pipeline
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/bhb build          # straive + pdf years + V-Smart → build/records.jsonl
.venv/bin/pytest
```

`bhb build` is the same sequence as `bhb ingest straive`, `bhb ingest pdfvol`, `bhb ingest vsmart` and `bhb merge`. Derived files go to `build/` (git-ignored). 1964–1965 are read from `data/interim/print-pdf/`. 2008 is rebuilt from `data/raw/pdf/BGB_2008.pdf` when that file is present.

```bash
.venv/bin/bhb gold sample          # 300 print entries → data/curated/gold/sample.xlsx
.venv/bin/bhb gold score           # intern 1992 sheets, or data/curated/gold/gold.xlsx once it exists
.venv/bin/bhb bench build         # synthetic 270k FTS5 database → build/bench/
```

The browser timings for that database are described in `bench/README.md`.

## Modules

### `bhb.ingest.jats` — STRAIVE years and PDF years

Reads `BGB_YYYY.xml`. Vendor tags fill the record when they exist; a plain-text citation parser is used for PDF years (no inline tags). Section paths are rebuilt from heading numbers. Print numbers that fall outside their neighbours are repaired.

### `bhb.ingest.pdf_volume` — BGB 2008

Born-digital yearly PDF (no outline). Writes `data/interim/print-pdf/BGB_2008.xml` in the same plain-text JATS shape as the Persée recovery.

### `bhb.ingest.vsmart` — catalogue exports 2009–2017

### `bhb.ingest.persee_pdf` — print volumes from Persée PDFs

Rebuilds one BGB year from the decade PDFs on rbph-btfg.be into the same JATS-like structure as the
STRAIVE files (nested `<ref-list>` sections, one `<ref>` per printed entry), so that every year can
flow through the same downstream steps. Used for **1964 and 1965**, which STRAIVE did not deliver.

```bash
python -m bhb.ingest.persee_pdf ../data/raw/pdf/BGB_1960-69.pdf 1964 \
    --headings-from ../2023-12-29/BGB_1960-69 \
    --out ../data/interim/print-pdf/BGB_1964.xml
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
