# Implementation plan — phase 2: one categorisation, public on GitHub Pages

Version 1.0 — 11 October 2026. Product owner: Mike Kestemont. This plan follows a review of the working tree at
commit `d72e830`. It replaces the line "category crosswalk postponed" in the internal project plan and the non-goal "fine-grained
mapping of old sections onto modern BHB codes" in `docs/PROTOTYPE_SPEC.md` §7. Everything else in those two files
still holds.

**Principle for this phase:** keep it light. One static site, one CI workflow, two small curated CSV files, one
small local classifier. No server, no new front-end framework, no LLM API.

---

## 0. What the review found (verified on `build/records.jsonl`, 11 Oct 2026)

| # | Finding | Effect |
|---|---|---|
| 1 | The site's "Theme" is `section_path[-1]`. V-Smart records have no `section_path`. | All ≈46,000 records of 2009–2017 show no theme. Their `bhb_codes` (with FR/NL labels in `build/bhb_codes.json`) are never shown. |
| 2 | `bhb/sections.py`: an unnumbered heading becomes a child of the *previous heading*, not of the previous *numbered* heading (its own docstring says the latter). | Sibling headings stack up: 37 % of print entries have a path deeper than 6 levels (maximum 27). Example: 1955, "La dynastie… > La politique intérieure > Les mouvements ouvriers > … > L'Expansion coloniale". |
| 3 | A single `I.` is read as Part I unless the previous capital letter is `H.`. | "I. Brabant, Limbourg, Outre-Meuse, Malines" (a regional sub-section) is a top-level part in 1972, 1973 and 1990. ≈3,900 entries get period `aux` (auxiliary sciences). |
| 4 | "(Voir aussi – Zie ook: 8447)" lines are pushed as headings. | Wrong paths for 2.3 % of print entries. They are really *secondary categories* for the entries they list, and that is lost. |
| 5 | The 2008 PDF reader takes some citations for headings ("XI. 2004. Bruxelles; Brussel, Institut historique …", "V. Dhondt. Memorial Volume …"). | ≈2,300 of 3,454 entries in 2008 sit under a wrong heading; 1,002 have no period. |
| 6 | `is_cross_listing` is never true (0 in every year of `build/ingest_report.md`). | The cross-listing signal described in the internal project plan §1 is unused. Check whether detection or the report is wrong. |
| 7 | 1993–2007 headings use the modern numbering. Codes rebuilt from the heading numbers agree with the label in `build/scheme.json` for 81–100 % of entries, but only 50–76 % reach depth ≥ 3 (because of #2 and #4). For 1990 the numbers also match a code while the label does not (7 % agreement). | Numbers alone cannot be trusted. Every number-derived code must be checked against the label. |
| 8 | Places, language, similar items, PDF page links for 1952–2007: 0 % coverage. | Not part of this phase (see §6). |
| 9 | Site assets and Pagefind are loaded from absolute paths (`/pagefind/pagefind.js`, `/crh-logo.svg`, `/marks/…`); `vite.config.ts` sets no `base`. | Search and images break under `https://mikekestemont.github.io/bebibhist/`. |
| 10 | The Pagefind index is ≈175 MB in ≈180,000 files (one fragment per record). `du` shows 756 MB because of block size. | Fine for Pages (1 GB limit). It must never be committed: deploy as a Pages artifact from CI. |
| 11 | `index.html` loads the Commission's Adobe Typekit kit (`zzy3ddc`). | Kits only serve registered domains, so github.io falls back silently; using another organisation's kit is also a licence question. |
| 12 | The GitHub repository is **private**. | Pages on a private repository needs a paid plan. Mike decides. |
| 13 | Dead weight: `bench/` (sql.js-httpvfs, rejected), `pipeline/bhb/bench.py`, `build/bench` (657 MB local), an empty untracked `package-lock.json` at the root. The index in `site/public/pagefind` is older than the code (the internal project plan §9, item 1). | Clutter; stale search results. |

---

## 1. Phase A — Deployable on GitHub Pages (≈1 day)

A1. **Relative base.** Set `base: "./"` in `site/vite.config.ts`. Load every asset through
`import.meta.env.BASE_URL` (Pagefind: `` `${import.meta.env.BASE_URL}pagefind/pagefind.js` ``; crest and marks the
same way). Hash routing means the document is always `index.html`, so a relative base works at any sub-path and on a
later custom domain. Check with `npm run build && npx vite preview --base /bebibhist/`.

A2. **Fonts.** Remove the Typekit `<script>` from `site/index.html`. The CSS already has fallback stacks (Palatino /
Georgia for Sabon, Avenir Next Condensed / Arial Narrow for Proxima Nova). Mike asks the Commission whether the
domain may be added to their kit; if yes, it is one line to restore.

A3. **CI workflow** `.github/workflows/pages.yml`, triggered by `workflow_dispatch` and by pushes to `main` that
touch `pipeline/`, `site/`, `data/curated/`, `2023-12-29/`, `exports Rijksarchief/` or `data/interim/`:
1. checkout; `actions/setup-python` (3.12, pip cache); `pip install -e "pipeline[classify]"`;
2. `bhb build` (needs no PDF: `data/interim/print-pdf/*.xml` is committed; the PDF is only used to regenerate it);
3. `actions/setup-node` (22, npm cache); `cd site && npm ci && npm run index && npm run build`;
4. a size check that fails the job if `site/dist` exceeds 900 MB;
5. `actions/upload-pages-artifact` (path `site/dist`) and `actions/deploy-pages`.
Use `concurrency: pages` and the permissions `pages: write`, `id-token: write`. Record the wall time of each step in
the job summary. Never commit `site/public/pagefind` or `site/dist` (already in `.gitignore`).

A4. **Clean-up.** Delete `bench/`, `pipeline/bhb/bench.py`, `pipeline/tests/test_bench.py` and the `bhb bench`
commands; keep `docs/BENCHMARK.md` as the record of why. Delete the empty root `package-lock.json`. In
`docs/PROTOTYPE_SPEC.md`, mark §6.2 (SQLite data layer) and the `bhb export sqlite` step as superseded by Pagefind.

A5. **Rebuild** `bhb build` and the index once, so the site matches the code (the internal project plan §9, item 1).

Done when: `vite preview` under `/bebibhist/` searches, shows the crest and opens a record; the workflow file
passes `actionlint` (or a dry run on a fork/branch); nothing under `build/` or `site/public/pagefind` is tracked.

---

## 2. Phase B — Correct the printed heading tree (1–2 days) — prerequisite for phase C

B1. **Unnumbered headings** (`bhb/sections.py`). An unnumbered heading takes the level *last numbered heading + 1*
and replaces any unnumbered heading already at that level. Fix the docstring/code mismatch. Regression test with the
1955 example above: "L'Expansion coloniale" must be a sibling of "Les mouvements ouvriers", not its grandchild.

B2. **Top-level parts.** A roman numeral is a level-1 part only if its text matches a known part title of that era
(FR or NL, accent-folded): Généralités / Algemeenheden, Bibliographies et sciences auxiliaires, Travaux généraux /
Algemene werken, Histoire par époques / Geschiedenis in tijdvakken, and whatever else the volumes use (list them
from the data and put the list in the code). Otherwise it is the letter `I` at level 2. Test: "I. Brabant,
Limbourg …" in 1972, 1973 and 1990 is level 2.

B3. **"Voir aussi / Zie ook / Cfr." lines** are not headings. Parse the numbers they list, resolve them to ids within
the same BGB year, and give each target a *secondary section*: new field `secondary_sections: list[list[str]]`
(the full path of the section where the pointer stands). Unresolvable numbers get the flag
`see-also-unresolved`.

B4. **2008 PDF headings** (`bhb/ingest/pdf_volume.py`). 2008 uses the modern scheme, so accept a line as a heading
only if its number pattern fits the scheme *and* its text is close to a heading label known from 2005–2007 or
`build/scheme.json` (rapidfuzz `token_set_ratio ≥ 80`, accent-folded). Regenerate
`data/interim/print-pdf/BGB_2008.xml` locally (the PDF is in `data/raw/pdf/`, not in git) and commit it.

B5. **Cross-listings.** Find out why `is_cross_listing` is never true (detection in `bhb/ingest/jats.py:330` or
the counting in `bhb/merge.py`). Fix whichever is wrong, with a test.

B6. **Heading report.** Add to `build/ingest_report.md`, per BGB year: distinct paths, maximum depth, share of
entries with depth > 6, level-1 headings not in the B2 list, share without period. The `bhb build` command prints a
warning when a year has a level-1 heading outside the list or a depth > 8.

B7. Re-run the period rules (`bhb/facets.py`) on the fixed paths. Match `1789` only in a heading that also names an
era (not in any heading that happens to contain a date).

Done when: no year has depth > 8; no level-1 heading is outside the list; the "I. Brabant" entries are no longer
`aux`; 2008 has ≥ 95 % period coverage; tests for B1–B5 pass. **Stop and report the B6 table to Mike before phase C.**

---

## 3. Phase C — One categorisation for all years (≈1 week of work + human review)

### C1. Target vocabulary

The **modern BHB scheme** (the one in V-Smart and printed since 1993) is the only target. Write it as
`data/curated/scheme.csv` (`code, parent, label_fr, label_nl, label_en, source`), seeded from `build/scheme.json`.
That file only holds codes that V-Smart records use (198); add the codes printed in 1993–2007 headings that are
missing (`source = print-1993+`). English labels are drafts written by the agent and marked as such in a `note`
column; the editor or Mike review them. (A SKOS version is a later step.)

### C2. Two uniform facets: period × theme

Every code resolves to a **period** (the 7 existing values; rules already in `bhb/facets.py`) and to one or more
**themes** through `data/curated/theme_map.csv` (`code_prefix, theme`; the longest matching prefix wins). A pytest
checks that every code in `scheme.csv` resolves to at least one theme. Proposed themes (at most 10):

| value | FR | NL | EN | typical codes |
|---|---|---|---|---|
| `reference` | Bibliographies et sciences auxiliaires | Bibliografieën en hulpwetenschappen | Reference and auxiliary sciences | `I.` |
| `general` | Travaux généraux et historiographie | Algemene werken en historiografie | General works and historiography | `II.A`, `II.B`, period headings without a sector |
| `local` | Histoire locale et régionale | Lokale en regionale geschiedenis | Local and regional history | `II.C` (plus the sector theme where the sub-code names one) |
| `political` | Institutions, politique, droit, guerres | Instellingen, politiek, recht, oorlog | Institutions, politics, law and war | sector a; dynasty; military events |
| `economic` | Vie économique | Economisch leven | Economic life | sector b |
| `social` | Histoire sociale et démographie | Sociale geschiedenis en demografie | Social history and demography | sector c; demography |
| `religious` | Vie religieuse et laïcité | Religie en vrijzinnigheid | Religion and secularism | sector d |
| `cultural` | Culture, enseignement, sciences, arts | Cultuur, onderwijs, wetenschap, kunst | Culture, education, science and arts | sector e/f; archaeology |

The sector letters differ between periods (e.g. `III.C.1.b` vs `III.D.2.a` for institutions): map from the labels,
not from the letters. Themes are multi-valued. The editor or Mike review `theme_map.csv` (≈200 rows).

### C3. Record model

Add to `Record` (`bhb/model.py`), keeping `section_path` and `bhb_codes` as they are:

```jsonc
"categories": [
  {"code": "III.D.2.a.", "source": "vsmart",          // vsmart | heading-rule | crosswalk | see-also | classifier
   "confidence": 1.0, "machine": false, "primary": true}
],
"theme": ["political"],           // derived from categories, for the facet
"period": ["contemporary"]        // derived from categories, plus the existing path rules
```

A category may have `code: null` and only a theme (see C6). `machine: true` for anything not set by a person or
by the printed volume itself.

### C4. One heading-level crosswalk for every print year

`bhb categorise draft` writes `data/curated/heading_crosswalk.csv`, one row per **distinct normalised heading
path** (accent-folded, footnote marks, OCR spaces and date ranges like "1789–1972" removed; FR half of a bilingual
heading as key):

`era, heading_key, example_fr, example_nl, years, n_entries, proposed_code, proposed_by, proposal_confidence,
second_code, second_confidence, approved_code, approved_theme, reviewer, note`

- **1993–2008:** `proposed_code` from the heading numbers; `proposed_by = numbers+label` and auto-approved
  (`approved_code` filled, `reviewer = rule`) only if the label agrees (`token_set_ratio ≥ 70` against the scheme
  label). Otherwise `proposed_by = numbers` and it waits for review.
- **1952–1992** (two older schemes, ≈69,000 entries): `proposed_code` from the classifier, aggregated over the
  entries under that heading (C5). The old heading's period (from the fixed path rules) restricts the candidate
  codes to that period.
- Sorted by `n_entries`, descending, so a reviewer can stop once most entries are covered. The file states, at
  the top of a companion `heading_crosswalk.README.md`, how to fill `approved_code` / `approved_theme` and that
  an empty `approved_code` means "not reviewed".
- `bhb categorise draft` never overwrites a filled `approved_*` or `reviewer` cell; it only refreshes proposals.
- Headings that are genuinely broad ("Généralités", "Travaux généraux", a whole region) may be approved with
  `approved_code = BROAD`: their entries are then classified one by one (C6).

### C5. Classifier (local, scikit-learn, no LLM)

- **Input text:** title, subtitle, translated title, host title, note. Not the heading text (it differs per era).
- **Labels:** codes truncated to depth 4 (e.g. `III.D.2.e.`); a class with < 30 training entries is merged into its
  parent.
- **Training data:** V-Smart 2009–2014 + print 1993–2004 with an approved heading code. **Held-out:** V-Smart
  2015–2017 + print 2005–2008 (split by year, so near-duplicates of a series do not leak).
- **Model:** `TfidfVectorizer` (word 1–2-grams, `sublinear_tf`, `min_df=2`) + `TfidfVectorizer` (`char_wb` 3–5)
  in a `FeatureUnion`, then `LogisticRegression` (multinomial, fixed `random_state`). It must train in a few minutes
  on a laptop CPU and in CI. Add `scikit-learn` as the optional extra `classify` in `pipeline/pyproject.toml`.
- **Theme and period probabilities** are the sums of the code probabilities that map to each theme / period.

### C6. Confidence thresholds (required)

A machine value is stored only above a minimum probability; below it, the entry stays unclassified (an explicit
"Not classified / Niet geclassificeerd / Non classé" value in the facet). Nothing is guessed below threshold.

| Level | Rule | Default |
|---|---|---|
| Code from the classifier | `p(code) ≥ τ_code` | τ_code = 0.70 |
| Theme from the classifier (without a code) | `p(theme) ≥ τ_theme` | τ_theme = the smallest value with **≥ 90 % theme precision** on the held-out set, and **never below 0.60** |
| Heading proposal in the crosswalk | mean `p(code)` over the heading's entries ≥ 0.50 and `n_entries ≥ 5`; otherwise the row is left without a proposal | — |
| Unreviewed heading proposal used on the site | only if the heading proposal confidence ≥ 0.80; stored as `source = crosswalk`, `machine = true` | — |

Thresholds live in one place (`bhb/categorise.py` constants, overridable by CLI flags) and are written into the
report. The **held-out set is modern**, so it overstates accuracy on 1952–1992. Add 100 pre-1993 entries with a
`theme` column to the P3 gold sample (`bhb gold sample`); until that sheet is corrected, every pre-1993 machine theme
is shown as "suggested".

### C7. Precedence (first match wins for the primary category; the rest are kept as secondary)

1. `approved_code` / `approved_theme` in the crosswalk (person) or the heading rule with label agreement (1993–2008);
2. V-Smart `bhb_codes`;
3. `see-also` secondary sections, resolved through the same crosswalk (always secondary);
4. unreviewed crosswalk proposal ≥ 0.80 (`machine`);
5. classifier above threshold (`machine`), for entries under `BROAD` or unmapped headings;
6. otherwise unclassified.

### C8. Report

`build/classification_report.md`, per BGB year and source: share with ≥ 1 theme, split by origin (person /
rule / V-Smart / machine), share unclassified, and the held-out precision and coverage at the thresholds used.
Target: **≥ 90 % of entries with a theme in every year, ≤ 25 % of them machine-derived**; report, do not force.

### C9. MODS

One `<classification authority="bhb">` per code; `usage="primary"` on the primary one; machine-derived ones get
`displayLabel="machine-suggested"`. Validate against the MODS 3.8 XSD as before.

---

## 4. Phase D — Site (1–2 days)

D1. Facets: **Period** (fixed) and **Theme** (new) above type. Show the "Not classified" value. Labels in FR/NL/EN
in `site/src/i18n/*.json`. The source and decade filters go (see E3, E4).

D2. Record page: the category label of the most specific known code in the page language, then "Theme as printed:
…" with the printed heading (print entries only). A machine-derived category carries a small "suggested"
(suggéré / voorgesteld) marker with a tooltip that says how it was obtained. V-Smart records now show their
category.

D3. Payload budget: Pagefind loads the filter and sort metadata (≈5 MB today) on the first search. Report its size
after the changes in D1 and E3–E4 (theme and publication year in; source, decade and the BGB-year filter out). Do not
add other filters in this phase. Target ≤ 6 MB.

---

## 4b. Phase E — Search and result list (Mike's requests, 11 Oct 2026)

Several of these follow the BNTL (Bibliografie van de Nederlandse Taal- en Literatuurwetenschap,
https://bntl.flw.uantwerpen.be), a project Mike worked on. Copy the interaction patterns, not the look: our styling
stays.

E1. **Fonts.** Since the Typekit kit was dropped (commit `f8fb9cd`), the fallback stacks resolve to different faces
on Mac, Windows and Android, so the site looks inconsistent. Self-host two open (SIL OFL) families as `woff2` in
`site/public/fonts/`, loaded with `@font-face` and `font-display: swap`, and use them everywhere (headings, body,
citations, buttons, inputs, selects; `font: inherit` already covers form controls):
- **EB Garamond** (regular, italic, semibold) for the citations and headings now set in Sabon. Sabon is a Garamond
  revival, so the tone is kept.
- **Barlow Semi Condensed** (regular, medium, semibold) for the interface now set in Proxima Nova Condensed, and
  **Barlow Condensed** (semibold) for the green menu bar now set in Proxima Nova Extra Condensed.
Subset to Latin + Latin-1 + Latin Extended-A (Dutch, French, German, Latin names); target ≤ 250 KB for all files
together. Keep each licence file next to the fonts. Do not load fonts from Google's CDN (a third-party request on
every visit). If the Commission later registers the domain for their kit, the Typekit names go back in front of these
stacks.

E2. **Sizes.** The main column has become too small: much of it is `0.75rem` on a 14px root (≈10.5px). Leave the
header and footer as they are. In the main column: result citations ≥ 16px, record-page fields ≥ 15px, facet labels
and counts ≥ 14px, small print (counts, sort, pager, export) ≥ 13px. Check at 375px width and at 1440px.

E3. **Publication-year range filter** in the "Refine / Verfijnen / Affiner" column, replacing the decade filter.
- Data: a new Pagefind filter `pubyear` with one value per year. Use the publication year (89 % of entries have
  one). If there is none, or it falls outside 1945–the current year (a few hundred values, mostly editions of old
  sources or parse errors), use the BGB year and mark the record with the flag `year-from-volume`. The record page
  says "year of the volume" in that case.
- Control: two handles on a slider (from / to), plus two number fields where a year can be typed. Above the slider, a
  small histogram of the hit counts per year (or per 2–5 years when narrow), drawn as plain SVG bars from the counts
  Pagefind returns for the `pubyear` filter, like the price histogram on Airbnb. Bars outside the selection are
  greyed out.
- Query: `filters: { pubyear: { any: [from … to] } }`. The range goes into the URL hash, so it survives reloads and
  can be shared. Works without a query text too (`pagefind.search(null, { filters })`).
- The BGB year stays available as a sort order. This replaces the decision that the two chronologies are only sort
  orders.
- Keyboard: arrows move a handle by one year, PageUp/PageDown by ten; both fields have labels.

E4. **Remove the source filter** ("Bron / Source"). The source stays on the record page and in the exports.

E5. **Search field selector.** Next to the search box, a small dropdown: *All text* (default) · *Author* · *Title* ·
*Journal / book* (the host). Pagefind has no fielded search, so add field tokens to the indexed content: every
accent-folded word of the title is also written as `ti_<word>`, every person name as `au_<word>`, every host
title word as `in_<word>` (the index keeps `_` inside words, see `pagefind-entry.json`). A field search rewrites each
query word to its prefixed form. These tokens are never shown, since a result shows the citation from metadata,
not an excerpt. Measure the index growth and report it; if the index grows by more than 50 %, index title words
only for titles and authors only by family name.

E6. **Inline expansion.** Each result gets a chevron on the right (as on the BNTL). Clicking the row or the chevron
opens the record's parsed fields in place, under the citation, with: the category (D2), export and a link to the
permanent record page. (A "Similar publications" button waits for E8.) Only one row is open at a time; `Enter`/`Space` toggle,
and `aria-expanded` is set. The record page stays the permalink.

E7. **Search within results.** A second, smaller box above the list: "Search within these results". It adds words
to the current query (Pagefind matches all words) and keeps the filters. Each refinement is shown as a removable
chip next to the original query, and is kept in the URL hash.

E8. **Similar publications — deferred (Mike, 11 Oct 2026).** Not in the review version; it needs a separate proposal (method, quality check, presentation) before any work. The sketch below is kept only as a starting point for that proposal.

~~Similar publications~~ (replaces the embeddings in `docs/PROTOTYPE_SPEC.md` P4.7 for now). At build time,
in the pipeline (scikit-learn, already a dependency): a TF-IDF matrix over the title, subtitle and translated title
(accent-folded; word 1–2-grams; stop words removed for FR, NL, EN, DE; `min_df=2`). Add the record's theme as one
extra token, so topic counts a little. Compute the top 5 cosine neighbours per record in chunks of sparse matrix
products, excluding the record itself and its cross-listings. **Keep a neighbour only if cosine ≥ 0.30**
(adjust after a spot check of 30 random records, and log the value); a record may have no neighbours, and then the
button is not shown. Store the ids in the record's `similar` field and in the Pagefind metadata. In the browser, the
button fetches those few records by id and lists them inside the expanded row. Call it "Similar publications /
Publications similaires / Gelijkaardige publicaties" with a small icon, not "AI". It must run in a few minutes in
CI; report the time.

E9. **Type icons.** A small inline SVG icon before each result for its type: article, chapter, book, journal issue,
other. One colour, ≈16px, with a text label for screen readers and as a tooltip. No icon font.

E10. **Results per page:** 10 / 20 / 50 / 100 (default 20), next to the sort control, kept in the URL hash.

E11. **Author links.** In an expanded row and on the record page, each person's name is a link that runs an author
search (E5) for that name as printed (family name + initials). A tooltip says that names are matched as written:
namesakes are not separated and spelling variants are not joined. Identifying persons is still a later pass.

Not copied from the BNTL: its background, its Bootstrap look, and the "AI" label.

---

## 5. Order, effort and stop points

| Step | Effort | Stop point |
|---|---|---|
| A1–A5 deployable site | ≈1 day | Mike enables Pages |
| B1–B7 heading tree | 1–2 days | **report the B6 table to Mike** |
| C1–C2 scheme and theme map | 1 day | Mike / the editor review `theme_map.csv` |
| C3–C9 crosswalk draft, classifier, thresholds, report | 3–4 days | **report C8 to Mike**; crosswalk goes to the editor |
| D1–D3 site | 1–2 days | deploy |
| E1–E2 fonts and sizes | ½ day | **do these first**, right after the step in progress |
| E3–E11 search and result list | 3–4 days | after D, or while waiting at a stop point; report index size and first-search payload |
| Human review of `heading_crosswalk.csv` | 2–4 days (the editor) | rebuild; nothing in code changes |

Commit per step, with tests. Record every decision you take yourself in `docs/DECISIONS.md` (one line, with the
reason). Keep `printed` untouched. Update the internal project plan §9 at the end.

---

## 6. Not in this phase

Places, language detection, embedding-based similar items (TF-IDF neighbours are in E8), PDF page links for
1952–2007, XLSX/CSV export, an advanced search form with several fields at once (E5 offers one field at a time), person/journal identification, the map. They stay in the internal project plan and `docs/PROTOTYPE_SPEC.md` P4–P6
for the next phase.
