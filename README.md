# Bibliography of Belgian History — unified search (BHB-BGB)

*Bibliographie de l'Histoire de Belgique / Bibliografie van de Geschiedenis van België*, compiled under the Royal
Commission for History (KCG-CRH). This repository turns the retro-digitised print volumes (1952–2008) and the
digital-born records from the State Archives' catalogue (2009 →) into one dataset and a free, static search
website.

**Status: prototype for review (October 2026).** The site is not indexed by search engines yet, and much of the
parsing and categorisation still needs checking.

- **[docs/PROTOTYPE_SPEC.md](docs/PROTOTYPE_SPEC.md)** — implementation brief (sources, record model, site).
- **[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)** — current work.
- **[docs/DECISIONS.md](docs/DECISIONS.md)** — decision log.
- **[pipeline/](pipeline/README.md)** — Python package `bhb` (data pipeline).
- **[site/](site/README.md)** — the search website (Vite, Svelte, Pagefind).

## How it is built

The raw deliveries are not in this repository. They live in a private folder that the pipeline reads through
`BHB_RAW` (default `../bebibhist-raw`). With access to it:

```bash
cd pipeline && python3.12 -m venv .venv            # Python 3.12, see pipeline/.python-version
.venv/bin/pip install -r requirements.lock && .venv/bin/pip install --no-deps -e .
.venv/bin/bhb build      # → build/records.jsonl
.venv/bin/bhb release    # → build/release/records.jsonl.gz + NOTES.md
.venv/bin/pytest         # runs without the raw folder too
```

A `data-YYYY-MM-DD` release with `records.jsonl.gz` triggers `.github/workflows/pages.yml`, which builds the
search index and the site and deploys them to GitHub Pages. No raw data are needed for that step.

## Credits

The "similar publications" feature (the magic-wand button) borrows its idea and set-up from the search engine that
**Enrique Manjavacas** built for the BNTL, the *Bibliografie van de Nederlandse Taal- en Literatuurwetenschap*
(https://bntl.flw.uantwerpen.be, code at https://github.com/emanjavacas/bntl). It encodes each record once with a
sentence-embedding model and lists a record's nearest neighbours as an ordinary result list. Here the neighbours are
precomputed with a local multilingual model and shipped as static files, not served from a vector database. The
result list (inline expansion, search within results, type icons, results per page, author links) also follows the
BNTL's interaction patterns.

## Licence

The bibliography as a whole — site and downloads — is **CC BY-NC 4.0**
(https://creativecommons.org/licenses/by-nc/4.0/): reuse with attribution to the Royal Commission for History,
non-commercial only. Code: MIT.
