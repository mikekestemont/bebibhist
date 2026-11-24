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
.venv/bin/bhb candidates vabb  # VABB-SHW candidates for 2018–2023, for review in a Zotero inbox (internal: not on the site, not in a release)
.venv/bin/pytest
```

`requirements.lock` is compiled from `pyproject.toml` with every extra (`dev`, `classify`, `embed`, `lock`). After changing a dependency, run `.venv/bin/pip-compile --extra dev --extra classify --extra embed --extra lock --strip-extras --allow-unsafe -o requirements.lock pyproject.toml`, then `.venv/bin/pip-sync requirements.lock` and `.venv/bin/pip install --no-deps -e .`. CI installs the `dev` extra with the lock file as constraints.

`bhb build` is the same sequence as `bhb ingest straive`, `bhb ingest pdfvol`, `bhb ingest vsmart` and `bhb merge`. `bhb merge` first applies the hand corrections of `data/curated/corrections.csv`, then the machine-found OCR corrections of `data/curated/ocr_persee.csv` (written by `bhb corrections persee` from the STRAIVE–Persée comparison; then the names misread by OCR of `data/curated/ocr_names.csv` (written by `bhb corrections names` from the names' spellings and KBR's authors in `build/external/kbr/`; it keeps the rows a build has already applied; kind `name` corrects the people's names only, never the printed citation); then the citation pass's OCR fixes of `data/curated/ocr_citation_pass.csv` (read in their printed context, 24 Nov 2026; kind `print`: the fields are corrected, the printed citation stays as printed; flagged `corrected-print-machine`); `bhb corrections apply` applies the four files to an existing build) (columns `id`, `wrong`, `right`, `kind` = `ocr`, `print`, `name`, `type` or `order`, `checked_by`, `date`, `note`): an `ocr` row corrects the text everywhere in the entry, the printed citation included; a `print` row corrects the parsed fields and leaves the citation as printed. An `order` row puts the people in the right order: `wrong` and `right` list their family names, separated by "; ", as the entry has them and as they should be. A row that no longer matches is reported on stderr. `bhb export mods` writes that record as MODS 3.8, one file per BGB year, under `build/mods/`. `bhb export skos` writes the BHB scheme, the periods and the subject areas as SKOS to `build/skos/bhb.ttl`, from `data/curated/scheme.csv`, `theme_map.csv` and `facets.csv`. Derived files go to `build/` (git-ignored).

Raw inputs are not in this repository. Set `BHB_RAW` to the folder that holds them, or place that folder at `../bebibhist-raw`. It contains `2023-12-29/`, `exports Rijksarchief/`, `data/raw/`, `data/interim/` and `legacy/`. A missing folder stops the ingest with one error that names `BHB_RAW`. 1964–1965 are read from `$BHB_RAW/data/interim/print-pdf/`. 2008 is rebuilt from `$BHB_RAW/data/raw/pdf/BGB_2008.pdf` when that file is present; the regenerated XML is written to `build/print-pdf/BGB_2008.xml`.

```bash
.venv/bin/bhb gold sample          # 300 print entries → data/curated/gold/sample.xlsx
.venv/bin/bhb gold score           # intern 1992 sheets, or data/curated/gold/gold.xlsx once it exists
.venv/bin/bhb release             # build/release/records.jsonl.gz and NOTES.md
```

`bhb chain` runs the chain below as one command, in this order (`bhb chain --list` numbers the steps; `--from` and `--to` take a number or label, `--map` makes the topic map's layout and names again, `--print` shows the commands); before the paid `citations run` it runs the dry run and stops when more requests than `--max-parse` and `--max-translate` (default 0) would be sent, and it stops at the first step that fails (log in `build/chain.log`).

A release is made from a full run: `bhb build`, then (when entries have changed) `bhb journals apply`, `bhb identifiers apply`, `bhb language apply` and `bhb citations run`, in that order: the pass leaves out the printed entries that have a DOI, so without the identifiers it sends other batches (on 23 Nov 2026, 4,920 requests not in the cache against 63), the identifiers of printed articles need their journal ids, and each request carries as a hint the language the local step read, which for a title of names comes from its journal (without the language every request misses the cache and is paid for again; the run stops when no entry has one); check with `bhb citations run --dry-run` before the run itself; then `bhb citations apply` (a run keeps the translation of a title whose text is unchanged since the last run, already checked, and translates and checks only the others; each row of `translations.jsonl` names its `source` title; `bhb citations run --dry-run` sends nothing and counts what would be asked) (the fields of the citation pass, `build/citations/run/`, in place of the parser's, flagged `parsed-llm`, unless they do not fit the printed entry: an answer whose title is mostly not printed there is refused (`llm-answer-refused`), a person or pages the text does not print keep the parser's (`persons-from-parser`, `pages-from-parser`), an "Ibid." entry keeps the host of the entry before, and a subtitle that repeats the journal or the title is dropped, and a title word the model changed silently is put back as printed unless it corrects a misreading, and an entry linked to its volume by "Cfr. n°" stays a chapter; and every title's machine translations into nl, fr and en, for search only; the printed text stays; the correction files are applied again afterwards, since the model read the uncorrected text; then the split ligatures and lost line-break hyphens the model copied into the fields are repaired where the printed texts show the right form, `bhb/repair.py`, and a chapter linked to its volume through "Cfr. n°" takes the volume's parsed imprint and year), then `bhb similar` (a build drops the neighbours), then `bhb facets apply` (suggested periods and subject areas, marked as suggested), then `bhb places apply` (the places of the printed indexes, 1993–2007, and for the other entries the Belgian places their title names, marked as suggested), then `bhb journals apply` once before the identifiers (a printed article's DOI was found in its journal by ISSN, which needs its journal id; without it the cached answer is not found and the DOI is lost), then `bhb identifiers apply` (DOIs, ISBNs and ISSNs from the Crossref and VABB-SHW matches in `build/identifiers/` and the DOIs set by hand in `data/curated/identifiers_by_hand.csv`, with journal names for articles whose journal record was not exported), then `bhb journals apply` ("Ibid." resolved, `data/curated/journals.csv`, a journal id per article; it runs once on a fresh build; it also links the same publication listed in two volumes of the Bibliography, `duplicate_of`, `bhb/duplicates.py`, so that the site shows it as one record), then `bhb language apply` (the language of publication read from the title or, for a title of names, its journal or volume, marked as suggested; needs the `language` extra; `bhb language score` checks it against `data/curated/language/sample.csv`), then `bhb topicmap apply` (each entry's place on the map of subjects and its finest region, from `build/topicmap/layout.npz`; `bhb topicmap layout` and `bhb topicmap names` make that file and `data/curated/topic_regions.json` again when the entries change much, about 5 minutes and two hours (`--remote`: through OpenRouter, minutes, about $0.10), the names cached in `build/topicmap/names-cache.jsonl`), then `bhb release`. The matches themselves come from `bhb identifiers match --source vsmart`, `--source print-straive` and `--source print-pdf` (add `--offline` to re-score from the cache after a rule change, without querying Crossref; after a fresh `bhb build`, run `bhb journals apply` first, since printed articles are looked for in their journal by its ISSN and a fresh build has no journal ids yet) and `bhb identifiers vabb` (with the VABB-SHW open data in `build/external/`); `bhb identifiers openlibrary` adds ISBNs for books from 1970 on (a work with one edition only); `bhb identifiers kbr-harvest` harvests KBR's Belgian Bibliography into `build/external/kbr/` by date windows (resumable, about a day; `bhb/kbr_harvest.py` also runs on its own, with Python 3.8 and no packages: `python3 kbr_harvest.py FOLDER`), and `bhb identifiers kbr` matches the books and collected volumes to it (`build/identifiers/kbr.csv`, `kbr-names.json`) and fetches each match's ermes record into `build/cache/kbr-ermes/` (`--offline` matches only); `bhb identifiers apply` then adds the KBR link, the ISBN and authors' given names written out; their Crossref answers are cached in `build/cache/crossref/`, so a rebuild does not query again. Set `BHB_CONTACT` to a contact address for Crossref's faster pool. `bhb release` does not publish anything. Before the release, run the deploy's search checks on the site built from these records, locally (`npm --prefix site run verify`: index, build, `vite preview`, `tests/search-checks.mjs`; about 15 minutes, or 3 with `-- --no-index` when the index is already built from them); a check whose count range the new data rightly leave is widened in the same commit. Then this command creates the data release (replace `YYYY-MM-DD` with the build date printed in `NOTES.md`):

```bash
gh release create data-YYYY-MM-DD build/release/records.jsonl.gz build/release/NOTES.md --title "BHB-BGB data YYYY-MM-DD" --notes-file build/release/NOTES.md
```

To publish the site built and checked here instead of building it again on GitHub's runner (with 290,000 records over an hour there, about 20 minutes here; 24 Nov 2026), commit everything under `site/` and `data/curated/` first, then `npm --prefix site run verify` and `npm --prefix site run pack`, which writes `build/release/site-dist.tar.gz` with `build-info.json` (the git trees of `site/` and `data/curated/` and the records' SHA-256), and add `build/release/site-dist.tar.gz` to the files of `gh release create`, with `--target` the commit it was built from. The workflow deploys that site only when the three match its commit and the release's records, after the same size and search checks; a release without it is built on the runner as before.

The citation clean-up pass (`bhb/citations.py`, plan §5c) is piloted before it runs in full; set `OPENROUTER_API_KEY` first. `bhb citations pilot --model ID [--model ID …]` sends batches of consecutive entries that hold an entry of the answer key (a Crossref DOI match, or a row of the interns' 1992 sheets), balanced by decade (`--per-decade`), scores the parser and each model per field, and estimates the cost of the full pass; `--single` also sends each keyed entry alone, `--reasoning low` asks for a reasoning effort. `bhb citations translate --model ID` translates a sample of titles per language, plus titles with historical terms, into a sheet for a hand check (`build/citations/translate-*.csv`). `bhb citations key --model ID --variant v4 --split dev` scores the parser and a prompt variant (`v3`, `v4`, `v4-draft`; `--batch-size`) on the hand-checked key `data/curated/citations/key.csv`; keep `--split test` for the final comparison. `bhb citations run` is the full pass: it parses the printed entries without a DOI or VABB match (and every collected volume) with prompt v4, then translates every title, the parsed ones from the model's title, for search only; answers, translations, a review list and a report go to `build/citations/run/` (`--years 1975` for a test run into `run-1975/`), and nothing in the records changes yet. It resumes from the cache and stops when the key runs out of credit. `bhb citations ocr` compares STRAIVE with the Persée digitisation of 1960–63 and 1966–69 (first convert each year with `python -m bhb.ingest.persee_pdf … --out build/persee/BGB_<year>.xml`), writes every word read differently with a verdict (`build/citations/persee-differences.csv`) and scores the model's OCR fixes on a sample. Answers are cached in `build/cache/citations/`, keyed on the whole request; reports go to `build/citations/`.

The search benchmark that chose Pagefind over browser SQLite is recorded in `docs/BENCHMARK.md`. The benchmark code itself has been removed.

## Modules

### `bhb.ingest.jats` — STRAIVE years and PDF years

Reads `BGB_YYYY.xml`. Vendor tags fill the record when they exist; a plain-text citation parser is used for PDF years (no inline tags). Section paths are rebuilt from heading numbers. Print numbers that fall outside their neighbours are repaired.

### `bhb.ingest.pdf_volume` — BGB 2008

Born-digital yearly PDF (no outline). Writes `build/print-pdf/BGB_2008.xml` in the same plain-text JATS shape as the Persée recovery. The PDF itself stays in the raw folder.

### `bhb.ingest.pdf_volume` for 2009–2017 — the printed yearly volumes

`bhb ingest pdfyears` reads `<raw>/data/raw/pdf/BGB_2009.pdf` … `BGB_2017.pdf` (sources and hashes in that folder's
`SOURCES.md`) into `build/pdfyears.jsonl`, not merged into the build: they hold the entries the V-Smart exports of those
years lack (about 27,000) and also most of those they have. The
numbered volumes (to 2015) use the reader of 2008; the unnumbered ones (2016, 2017) start an entry at the text
margin and number it by its place (`bhb:2016-p1`). Each entry takes its heading's scheme code by label, as the
manuscripts do. `bhb build --with-print-years` merges them; `bhb journals apply` then links each printed entry to the
catalogue's record of the same publication, which is kept (`duplicate_of`), so only the entries the catalogue lacks
show as records of their own.

### `bhb.ingest.vsmart` — catalogue exports 2009–2017

### `bhb.ingest.manuscript` — the editor's Word manuscripts (2018–2023)

`bhb ingest manuscript` reads the newest `.docx` per year in `<raw>/manuscripts/` (`BGBBHB2020def.docx` and the
like: the editor's manuscripts in the old print layout, never printed) into `build/manuscript.jsonl`, and prints a
report per file. The notice before the first heading and the tables of contents after the last entry are skipped.
The rule parser reads each entry; the italic title, the italic book of a chapter and the bold authors then correct
it, with the flags `title-from-italics`, `host-from-italics`, `imprint-from-format` and `persons-from-bold`. Each
heading is matched by its label to a code of the BHB scheme (`HeadingCodes`, preferring a code under the open
heading above it), and its entries carry that code in `bhb_codes`, with the category source `heading-label`. Ids are
`bhb:<year>-m<10 hex digits>`, a hash of the entry's text, so an entry added to a revised manuscript moves no other id.
`bhb build --with-manuscripts` (or `bhb merge --with-manuscripts` after `bhb ingest manuscript`) merges them; without
the flag a build leaves them out, as it does by default, since the manuscripts are unpublished. Once merged they go
through the later steps like the other sources (`bhb identifiers match --source manuscript`; duplicates, VABB,
language, places, similar publications and the map take every record); the OCR corrections do not concern them.

Hosts missing from the V-Smart export: `bhb identifiers opac-hosts` fetches them from the State Archives' public
catalogue (`bhb.opac_harvest`), one request per 5 s, cached in `build/external/opac/`. `bhb merge` then names the
journal or book of each entry pointing at one (`host-from-catalogue`; an article in a book becomes a chapter) instead of
"[host record not exported]".

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
