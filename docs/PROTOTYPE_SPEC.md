# BHB-BGB search prototype — implementation brief

**Audience:** a developer or coding agent who has *not* seen any prior conversation. Everything you need is in this
file, `docs/IMPLEMENTATION_PLAN.md` (current work), `pipeline/README.md` (the one module that already exists) and the data
in this repository. **Product owner:** Prof. Mike Kestemont (University of Antwerp), member of the Royal Commission
for History of Belgium. Ask him when this brief says *ask*; otherwise decide, document the decision in
`docs/DECISIONS.md`, and move on.

Version 1.0 — 11 October 2026.

---

## 1. Context

### 1.1 What the bibliography is

The *Bibliographie de l'Histoire de Belgique / Bibliografie van de Geschiedenis van België* (abbreviated **BHB** in
French, **BGB** in Dutch; we use "BHB-BGB" or just "the bibliography") lists every year all publications (books,
articles, chapters, editions of sources, exhibition catalogues …) on the history of Belgium and the territories that
preceded it. It is compiled under the **Royal Commission for History** (*Koninklijke Commissie voor Geschiedenis /
Commission royale d'Histoire*, **KCG-CRH**, https://commissionroyalehistoire.be). It is fully bilingual
(French/Dutch) and every yearly volume is organised by a thematic/chronological **classification** (sections such as
"III. Histoire par époques > D. Époque contemporaine > 2. Histoire par secteurs > b. La vie économique > 5. Les finances").

- **1952–2017:** published every year in print inside the *Revue belge de philologie et d'histoire / Belgisch
  Tijdschrift voor Filologie en Geschiedenis* (RBPH-BTFG). Scans are on Persée and as PDFs at
  https://www.rbph-btfg.be/nl_biblio.html (decade PDFs 1952–2007, yearly PDFs 2008–2017).
- **2009 → today:** entries are also typed into the library catalogue of the **State Archives** (*Algemeen
  Rijksarchief / Archives générales du Royaume*, ARA-AGR), which runs **V-Smart Air**.
  Public interface: https://biblio.arch.be/airwebopac/www.main.cls?surl=BHBBGB (simple/advanced search on author,
  title, keyword; refine by year, material type, BHB keyword, co-author). From November 2026 new entries are
  *only* entered there (no more print volumes).
- Typical volume: 1,000–2,500 entries/year in the 1950s–80s, ≈4,000 in the 1990s–2000s, 8,000–9,700 since 2012.

### 1.2 Goal

One **free, static, modern search website** over the *whole* bibliography (retro-digitised print volumes + the
digital-born records), hosted on GitHub Pages, built locally, plus an **archival dataset** (MODS XML, CC BY-NC 4.0).
This brief covers the **prototype** that will be demonstrated to the Commission.

### 1.3 History (why things look the way they do)

- 2023: the print volumes 1952–2007 were OCR'd and marked up by an external vendor into JATS XML. Years **1964 and
  1965 were not in that delivery**.
- The retro-digitised years are not imported into the State Archives' catalogue; a MARC21 export can be produced
  on request.
- 2024: the State Archives exported BGB years 2009–2017 from the catalogue.
- 2026: an internship in the University of Antwerp's Master Digital Text Analysis flattened the XML into a CSV and
  clustered journal titles. Kept for reference in the private raw folder (`legacy/`), not used as code.
- 11 Oct 2026: 1964–1965 were recovered from the Persée PDF by `bhb.ingest.persee_pdf` (see `pipeline/README.md`).

### 1.4 Decisions already taken (do not revisit)

| | Decision |
|---|---|
| Hosting | GitHub Pages, repository under Mike's GitHub account; no server, no paid services. |
| Builds | Run locally (macOS, Apple Silicon). Python ≥ 3.10 is available (`python3`, miniconda). |
| Licence | Data **CC BY-NC 4.0 with attribution, on the whole bibliography** (every year, the site, every download). Commercial use is not permitted. Code MIT. |
| LLM APIs | **Not to be used** in the prototype. Local open models (embeddings) are fine. |
| Archival format | **MODS 3.8 XML**, one file per BGB year, written by the pipeline. |
| Search engine | **Pagefind.** The P1 benchmark rejected live SQLite-over-HTTP (`sql.js-httpvfs`): see `docs/BENCHMARK.md`. |
| Frontend | Vite + Svelte 5 + TypeScript, static build. |
| UI languages | French, Dutch and English, on equal footing. A language toggle is always visible. Default from the browser language, otherwise French. |
| Sources | Every source is an *adapter* to a common record. The State Archives' catalogue is read through its exports; nothing depends on a change of catalogue or on Zotero. |
| Scope of data | Prototype uses only data already in the repo (+ the 2008 PDF). It is labelled **beta**. |

---

## 2. Repository map (as found on 11 Oct 2026)

Since then the raw inputs (`2023-12-29/`, `exports Rijksarchief/`, `data/raw/`, `data/interim/`, `legacy/`) live in a
private folder outside this repository, read through `BHB_RAW` (default `../bebibhist-raw`). The map shows their layout.

```
bebibhist/
├── docs/PROTOTYPE_SPEC.md          this file
├── 2023-12-29/                     STRAIVE JATS XML, one folder per decade        → source A (read-only)
│   ├── BGB_1952-59/BGB_1952.xml … BGB_2000-07/BGB_2007.xml   (54 yearly files; 1964, 1965 absent)
│   └── BGB_1990-99/, BGB_2000-07/  + index/TOC fragments (place-name index, author index, journal lists, abbreviations)
├── data/
│   ├── raw/pdf/                    Persée PDFs (git-ignored; see SOURCES.md for URL + SHA-256)
│   └── interim/print-pdf/          BGB_1964.xml, BGB_1965.xml (+ .report.json)  → source A′
├── exports Rijksarchief/           V-Smart exports                                 → source C (read-only)
│   ├── f1450.xml (BGB 2009) f1449 (2010) f1448 (2011) f1447 (2012) f1446 (2013) f1445 (2014) f1444 (2015) f1443 (2016) f1440 (2017)
│   ├── f1441.xml                   1,043 journal ("tijdschrift") records linked to the BGB
│   └── alle tss titels.csv         13,998 journal titles in the ARA catalogue (latin-1, one column)
├── pipeline/                       Python package `bhb` (exists: bhb/ingest/persee_pdf.py)
└── Stage/                          internship notebooks and spreadsheets (reference only; now legacy/)
    ├── data_hardcoded/             STRAIVE files with small fixes (superscripts, brackets) — do NOT use as input
    ├── Notebooks/Duplicates/journal_final_with_external_matches_improved.xlsx   journal clustering (67k rows)
    └── Notebooks/Other_Gold_Standard /*.xlsx   40 hand-corrected 1992 entries (note the space in the folder name)
```

Never modify files under `2023-12-29/`, `exports Rijksarchief/` or `data/raw/`. Derived data goes to `data/interim/`
(git-ignored if > 20 MB) and `build/` (git-ignored).

---

## 3. Source data reference

### 3.1 Source A — STRAIVE JATS XML (1952–1963, 1966–2007; 126,847 entries)

Parse with `lxml` and `XMLParser(load_dtd=False, no_network=True, recover=True, resolve_entities=False)` (the
DOCTYPE points to a DTD that is not present). One file = one BGB year; take the year from the **filename**
(`BGB_1975.xml` → 1975), *not* from `<pub-date>` (contains `##`).

Structure:
```xml
<article><front>…volume metadata (contributors, fpage/lpage in RBPH)…</front>
 <body><p>…introduction…</p></body>
 <back>
  <ref-list id="bib1"><title>I. Bibliographies et Sciences Auxiliaires - Bibliografieën en Hulpwetenschappen</title>
   <ref-list id="bib2"><title>A. Bibliographies courantes … </title>
    <ref id="ref1"><label>47743</label>
     <mixed-citation publication-type="journal">
      <person-group person-group-type="author">
        <string-name><surname>Van Eenoo</surname> (<given-names>Romain</given-names>)</string-name>, …
      </person-group>. <article-title>Bibliographie de l'histoire de Belgique … 2004</article-title>.
      <source>Belgisch tijdschrift voor filologie en geschiedenis …</source>, <volume>LXXXIV</volume>,
      <year>2006</year>, <issue>2</issue>*, pp. <fpage>1</fpage>*–<lpage>270</lpage>*.
     </mixed-citation></ref>
```
Elements inside `mixed-citation` (counts over all files): `string-name/surname/given-names` (~162k), `person-group`
(`person-group-type` almost always `author`, even for editors), `collab` (227), `etal`, `source` (135k),
`article-title` (92k), `chapter-title` (5k), `trans-title` (22k; a translation of the title, usually in `[…]`),
`year`, `volume`, `issue`, `fpage`, `lpage`, `publisher-loc`, `publisher-name`, `edition`, `italic`, `bold`, `sup`,
`ext-link`, `uri`.

Known problems and required handling:
1. **Text is truth, tags are hints.** Always store `printed`: the `itertext()` of `mixed-citation`, whitespace-
   normalised, with `<sup>e</sup>` → `ᵉ` (and `er`, `re` similarly) so "XVIᵉ siècle" survives.
2. `publication-type` (`journal`, `book`, `other`, typos like `jounal`, `o`, `b`) is unreliable. Derive the type
   yourself: has `article-title` + `source` + (`volume` or `issue` or `fpage`) and no publisher → `article`;
   `chapter-title` or the text contains `In:`/`In :` → `chapter`; publisher present and no host → `book`; else
   `other`. Keep the vendor value in `provenance`.
3. `<source>` is also used (wrongly) for annotations after an em dash, e.g. `… — <source>Relevé exhaustif et
   critique</source>.` Rule: a `<source>` that follows ` — ` *after* the bibliographic part is an **annotation**
   (`note`), not the host title. Only the first `source` before the first ` — ` is the host/book title.
4. Page fields can hold several ranges (`pp. 37–48 ; 133–136`): keep the pages as printed string `pages`, and
   `fpage`/`lpage` of the first range.
5. **Labels** (print numbers) are mostly correct but some are OCR-garbled (`80048005`, `2345323768`). Numbers run
   monotonically within a volume (series restart in 1959 and 1993). Rule: if a label is not between its neighbours'
   labels, replace it by `prev+1` when that fits, keep the original in `provenance.label_raw`, flag
   `label-repaired`.
6. **Section hierarchy**: the nesting of `<ref-list>` is unreliable (e.g. 2005 nests part II inside part I). Rebuild
   it from the heading numbers: `I.`/`II.` (roman) > `A.`/`B.` (capital) > `1.`/`2.` > `a.`/`a)` > `1)`/`i.`;
   unnumbered headings ("Les villes — De steden") become children of the previous numbered heading. Store the
   path as a list of heading strings (`section_path`), cleaned of footnote markers like `(1)`. Perfection is not
   required; see §5 P4 for what the path is used for.
7. **Cross-references**: 10,945 entries contain `Cfr. n° 52358`, `Voir n°`, `Zie nr.` (often inside
   `trans-title`!). Extract the numbers into `cross_refs` (same volume unless a year is given) and remove them
   from the title fields. A `[Cfr. n° …]` entry with no other content is a cross-listing stub: set
   `is_cross_listing=true`, link it to the target, and **do not show it as a separate search hit**.
8. Bilingual heading strings: French and Dutch are separated by ` — `, ` - ` or nothing. Keep as printed.
9. Non-entry files in the decade folders (`Beknopte_Index…`, `Index_des_Noms…`, `II._Inhoudstafel…`,
   `Abreviations_Afkortingen.xml`, `II._Series_et_Revues…`) are **not** entries; see §3.4.

### 3.2 Source A′ — 1964 and 1965 from the Persée PDF (2,637 entries)

`data/interim/print-pdf/BGB_1964.xml` and `BGB_1965.xml`, produced by `bhb.ingest.persee_pdf` (see
`pipeline/README.md`). Same `<back><ref-list>…<ref>` structure as A, but `mixed-citation` holds **plain text only**
(`publication-type="unknown"`). Every `<ref>` carries `specific-use="pdf-page:403 print-page:1378"` and possibly
`content-type="check:…"` flags. Field extraction for these must come from the same rule-based parser you write for
A's plain text (§5 P2). Treat the report's known heading misses (1964 F.II; 1965 F.III and F.IV) as acceptable.

**Also recover 2008** (step P0): download `https://www.rbph-btfg.be/dowload_PDFs/BGB_2008.pdf` (≈3 MB) into
`data/raw/pdf/`, record its SHA-256 in `SOURCES.md`, inspect it (it is a yearly PDF, probably born-digital, without
the Persée outline), and adapt `persee_pdf.py` or write a sibling `bhb/ingest/pdf_volume.py`. If 2008 cannot be done
in two days, skip it and report why.

### 3.3 Source C — V-Smart exports (BGB 2009–2017; 46,542 records)

Flat XML, one element per field, field name = UNIMARC tag + Dutch label. Repeated fields are paired by the `Cnt`
attribute (the 2nd `_701a` belongs with the 2nd `_701b` and the 2nd `_7014`).

```xml
<BibDocumentsUniMarcB.Record Value="2^1214070">
 <_686vCoderingjaarinBHB-BGB Cnt="1">2013</_686vCoderingjaarinBHB-BGB>
 <_686aHoofdgeleding Cnt="1">II.C.1.d. Tijdvakoverschrijdende werken / Op regionaal en lokaal vlak / Thematische indeling / Abdijen; kloosters; …</_686aHoofdgeleding>
 <_686aHoofdgeleding Cnt="3">II.C.1.d. Travaux généraux / A l'échelon régional et local / Par secteurs fonctionnels / Les abbayes; …</_686aHoofdgeleding>
 <_700aEntryElement Cnt="1">Van De Perre</_700aEntryElement>
 <_700bPartofNameOtherthanEntryElement Cnt="1">Dirk</_700bPartofNameOtherthanEntryElement>
 <_200aHoofdtitel Cnt="1">De aankomst van de relieken van Sint-Adriaan te Geraardsbergen</_200aHoofdtitel>
 <_200bAlgemenemateriaalaanduiding Cnt="1">Artikel/Article</_200bAlgemenemateriaalaanduiding>
 <_210dDatumvanuitgavedistributieetc. Cnt="1">2013</_210dDatumvanuitgavedistributieetc.>
 <_4630 Cnt="1">Bib:2:16948</_4630>
 <_463vVolumenummer Cnt="1">2013, jg. LXV, nr. 4, p. 286-289</_463vVolumenummer>
 <Trefwoorden Cnt="1">…duplicate of 686a…</Trefwoorden>
</BibDocumentsUniMarcB.Record>
```

| Field | Meaning | Notes |
|---|---|---|
| `@Value` `2^N` | record id N | ID = `bhb:vs-N` |
| `_200aHoofdtitel` | title | |
| `_200eAnderetitelinformatie` | subtitle | |
| `_200dParallellehoofdtitel` | parallel title (other language) | |
| `_200bAlgemenemateriaalaanduiding` | `Artikel/Article` (article or chapter) | absent → book/monograph; `Tijdschrift/Revue` → journal |
| `_700a/_700b/_7004` | first person: surname / forename / role | roles: `Auteur`, `Onder leiding van` (editor), `Samensteller, uitgever` (compiler), `Voorwoord, nawoord`, `Vertaler`, `Illustrator` |
| `_701a/_701b/_7014` | further persons (repeatable, pair by `Cnt`) | same roles |
| `_710a/_710b/_7104`, `_711a` | corporate author | |
| `_210a` / `_210c` / `_210d` | place / publisher / year | |
| `_215a` | extent (`292 p.`, `2 Vol.`, `s.p.`) | |
| `_225a/_225v/_225e/_225d` | series title / number / other info / parallel | |
| `_4630` | link to host record `Bib:2:N` = record `2^N` | journal (in `f1441.xml`) or edited volume (in the yearly files) |
| `_463v` | volume/issue/pages as one string | formats vary: `2013, jg. LXV, nr. 4, p. 286-289`, `2015, 37, s.p. (en ligne)`; parse year and `p. X-Y` with regexes, keep the string |
| `_686a` | BHB classification: `CODE. NL path` and `CODE. FR path` (4 copies, mixed NL/FR, duplicates) | split code (`II.C.1.d.`) from label; dedupe by code; keep NL + FR labels; 1–6 distinct codes per record → **multi-label** |
| `_686v` | "BGB year" the record belongs to | mostly `YYYY`; garbage like `2017, tome 91, p. 5-36`, `070` → take the first 4-digit year if 2000 ≤ y ≤ 2030 else the file's year |
| `Trefwoorden` | duplicate of 686a | ignore |

Facts to respect:
- File → BGB year: f1450=2009, f1449=2010, f1448=2011, f1447=2012, f1446=2013, f1445=2014, f1444=2015, f1443=2016, f1440=2017. 5 record ids occur in two files: merge.
- Pooled over all files, **92% of host links resolve**; 539 distinct hosts are missing. Unresolved host → keep `host_id`, render "[host record not exported]".
- 1,710 records have no BHB code; 1,597 of them are referenced as hosts (edited volumes). Mark records with no `_686a` that are referenced as a host as `role="host"`: they complete citations but are **not search hits**. The remaining ≈113 uncoded records are normal entries.
- Exports are **incomplete** versus the printed volumes (2009: 1,004 of 5,642; 2017: 3,135 of 9,200; see the internal project plan §1.3). Do not try to fix this; show coverage honestly (§6.6).
- 176 distinct BHB codes occur; together with their NL/FR labels they define the **modern BHB scheme**. Emit it as `build/scheme.json` (code, parent code, label_nl, label_fr, count).

### 3.4 Auxiliary sources

- **Place-name indexes** (`2023-12-29/BGB_1990-99/Beknopte_Index_van_Plaatsnamen_…*.xml`, `BGB_2000-07/…Plaatsnamen…*.xml`, `Index_Sommaire…*.xml`): `<p>Antwerp: 21944, 22203 (Voir aussi - Zie ook: Antwerpen, Anvers)</p>`. Use them for (a) **synonym groups** (name + its "Voir aussi / Zie ook" names) and (b) **place tags**: the numbers are print numbers; assign each index file to a year by checking which volume's label range contains its numbers. Also derive synonyms for names that occur in several languages across indexes (Gand/Gent/Ghent, Liège/Luik, Anvers/Antwerpen/Antwerp, Louvain/Leuven, Malines/Mechelen, Bruges/Brugge, Mons/Bergen, Courtrai/Kortrijk, Tournai/Doornik, Namur/Namen; add a hand-made list `data/curated/place_synonyms.csv` of ≈60 major Belgian places in FR/NL/EN/DE to guarantee these).
- **Abbreviation lists** (`Abreviations_Afkortingen.xml`, front matter of volumes): `Ts.` = Tijdschrift, `Rev.` = Revue, `Bull.` = Bulletin, `Ann.` = Annales … Use for journal-title normalisation keys only; never rewrite the printed text.
- **ARA journal list** `alle tss titels.csv` (latin-1; header `"200/$a Hoofdtitel"`), and `f1441.xml` (1,043 journals, fields `_200a/_200e/_200d`).
- **Interns' journal clustering** `Stage/Notebooks/Duplicates/journal_final_with_external_matches_improved.xlsx` (columns `unique_id, title, title_clean, canonical_title, external_match, …`, row ids = row numbers of their CSV, *not* our ids): use only the `title → canonical_title / external_match` pairs as a lookup table, after spot-checking 50 pairs.
- **Gold standard**: only 40 corrected 1992 entries exist (`Stage/Notebooks/Other_Gold_Standard /*_corrected.xlsx`, columns `label, title, year, person_1…5, volume, issue, article_title, …`). Step P3 creates a larger one.

---

## 4. The common record (`BHB record`, version 0)

Every adapter emits JSON Lines (`build/records.jsonl`), one object per printed/catalogued **entry**. Use a Python
`dataclass`/`pydantic` model as the single source of truth and validate on write.

```jsonc
{
  "id": "bhb:1975-23701",            // print: bhb:<bgb_year>-<print number>[bis]; V-Smart: bhb:vs-<N>
  "source": "print-straive",          // print-straive | print-pdf | vsmart
  "bgb_year": 1975,                   // the volume / BGB year the entry belongs to
  "print_number": "23701",            // string (allows "8544bis"); null for vsmart
  "printed": "Dhondt (J.). … pp. 133-164.",   // print only: the citation exactly as printed (normalised whitespace)
  "type": "article",                  // article | chapter | book | journal-issue | other
  "title": "…", "subtitle": null,
  "title_translated": "[La toponymie en 1951]",  // print's bracketed translation, if any
  "persons": [{"family": "Dhondt", "given": "J.", "role": "author"}],  // roles: author, editor, compiler, translator, preface, illustrator
  "corporate": [],
  "host": {"title": "R. du Nord", "id": null, "volume": "XXXIV", "issue": "52", "year": "1952", "pages": "133-164", "subtitle": null, "editors": []},
  "series": {"title": null, "number": null},
  "publisher": {"place": "Bruxelles", "name": "…"},
  "year": 1952,                        // publication year (int) when determinable, else null
  "extent": "158 p.",
  "note": "Relevé exhaustif et critique.",   // annotations after " — "
  "language": "fr",                   // ISO 639-1 guess (fr, nl, de, en, la, it, es, other); see §5 P4
  "section_path": ["I. Généralités — Algemeenheden", "A. Instruments bibliographiques généraux …"],
  "bhb_codes": [],                    // modern codes, e.g. ["III.D.2.b.5."]; vsmart only in the prototype
  "period": ["contemporary"],         // facet, §5 P4
  "places": ["Antwerpen"],            // canonical place names (from index or matching)
  "cross_refs": ["bhb:1975-23650"],
  "is_cross_listing": false,
  "role": "entry",                    // entry | host
  "pdf": {"file": "BGB_1960-69.pdf", "page": 403, "print_page": 1378, "url": "https://www.rbph-btfg.be/dowload_PDFs/BGB_1960-69.php#page=403"},
  "provenance": {"file": "2023-12-29/BGB_1970-79/BGB_1975.xml", "xml_id": "ref123", "vendor_type": "journal",
                 "label_raw": "23701", "parser": "jats-rules@0.1", "confidence": 0.82, "flags": []},
  "similar": []                       // filled in P4: up to 10 ids
}
```

Rules: never drop an entry because parsing failed: fill `printed`, set the fields you are sure of, lower
`confidence`, add a flag. `confidence` ∈ [0,1] is your parser's self-assessment (e.g. share of the printed text
accounted for by extracted fields, penalised by anomalies).

---

## 5. Work steps

Implement as a Python package in `pipeline/bhb/` with one CLI entry point `bhb` (`argparse` sub-commands; add
`[project.scripts] bhb = "bhb.cli:main"` to `pipeline/pyproject.toml`). Steps must be re-runnable and deterministic.
Tests in `pipeline/tests/` (pytest). No notebooks.

### P0 — Repository hygiene (≤ 1 day)
- `git init` exists but has **no commits**. Before the first commit: keep `.gitignore` (already excludes the large
  CSVs and PDFs); check no file > 50 MB is staged (`Stage/sample/…xlsx` is 8 MB: fine).
- `git mv Stage legacy/stage-2026` (update the `Stage/…` paths in `.gitignore` accordingly) and add `legacy/stage-2026/README.md` (what the interns did, what is reusable:
  journal clustering, 40 gold entries; what not: the CSV).
- Keep `2023-12-29/` and `exports Rijksarchief/` where they are (paths are referenced); add a `README.md` in each
  saying where they come from (STRAIVE 2023; ARA exports, March and Aug 2024) and that they are
  read-only.
- Root `README.md`: one paragraph on the project + links to the internal project plan, this spec, pipeline/README.md.
- Recover 2008 (§3.2).
- **Done when:** first commit exists; `git status` clean; 2008 recovered or documented as postponed.

### P1 — Search engine benchmark (2–3 days, do before UI work)
- Generate a synthetic SQLite DB with 270k records resembling §6.2's schema (random titles from the real data are
  fine), with FTS5 and the facet table; split into 50 MB chunks; deploy to a test GitHub Pages repo/branch.
- Measure in Chrome and on a phone-sized throttled profile ("Fast 4G"): cold first query, warm query, bytes
  transferred, for (a) rare term, (b) frequent term (`histoire`), (c) frequent term + 3 facets with counts,
  (d) year-range only, (e) fetch 20 result rows, (f) export 2,000 rows.
- **Go** if (a)(b)(e) < 1.5 s warm and < 3 s cold, (c) < 3 s, and no query moves > 5 MB. Otherwise try mitigations
  (narrow facet table clustered by rowid, `page_size=1024`, limit facet counting to the first 5,000 hits and say
  "5,000+"), then fall back to Pagefind with JSON shards for records. Write the result in `docs/DECISIONS.md`.

### P2 — Adapters → `build/records.jsonl` (2–3 weeks)
- `bhb ingest straive` (A), `bhb ingest pdfvol` (A′ + 2008, reuse existing module), `bhb ingest vsmart` (C),
  then `bhb merge` → `build/records.jsonl` + `build/ingest_report.md` (counts per year and source, flags, label
  repairs, unresolved hosts).
- Plain-text citation parser (needed for A′ and as fallback/validator for A). Print citation conventions:
  `Surname (Given), Surname (Given) & Surname (Given). Title. [Translated title]. Host title, VOLUME (roman), place, year, issue, pp. X-Y. — Annotation.`
  Books: `Surname (Given). Title. Place, Publisher, year, 8°, ill., 158 p., 100 F.B. (Series, 12). — Annotation.`
  Editors appear as `(éd.)`, `(ed.)`, `(red.)`, `(dir.)`; `e.a.`/`et al.` = more authors; `s.l.`, `s.d.`, `s.p.`.
  Implement with ordered regexes + a small state machine; measure on P3's gold standard.
- Make the V-Smart adapter produce a `printed`-like display string too (Surname (Given). Title: Subtitle. In: Host, vol., year, p. X-Y.) so all records render alike. A part that already ends with a full stop does not gain a second one.
- **Done when:** every entry of A (126,847 minus cross-listing stubs counted separately), A′ (2,637) and C appears
  exactly once; IDs unique; ingest report generated; `pytest` passes (unit tests with ≥ 30 hand-written citation
  examples covering articles, books, chapters, editors, series, roman volumes, multiple page ranges, cross-refs).

### P3 — Gold standard and accuracy (1 week; needs a human)
- `bhb gold sample --n 300 --seed 2026` writes `data/curated/gold/sample.xlsx`: 300 random print entries
  stratified by decade (≈50 per decade), columns: `id, printed, type, title, persons, host_title, volume, issue,
  year, pages, publisher_place, publisher_name, note` pre-filled with the parser output.
- A human (Mike or a student) corrects it in Excel → `data/curated/gold/gold.xlsx`. *Ask* Mike to schedule this.
  Until then, use the 40 interns' entries as a smoke test.
- `bhb gold score` prints field-level exact-match accuracy per decade and source; add it to the build report.
- **Target for the prototype:** title ≥ 90 %, first-author surname ≥ 95 %, year ≥ 95 %, host title ≥ 85 %. Fields
  under target are **not** used as facets (they remain searchable as text).

### P4 — Enrichment without LLMs (2 weeks)
1. **Period facet** (coarse, from `section_path` for print and from `bhb_codes` for V-Smart). Values (labels in NL/FR/EN):
   `aux` auxiliary sciences & bibliographies (part I) · `general` cross-period / general works (part II) ·
   `ancient` prehistory → Carolingian · `medieval` medieval principalities · `burgundian` Burgundian dukes ·
   `early-modern` Habsburg / Spanish & Austrian Netherlands / Liège principality in modern times ·
   `contemporary` 1789 → present. Rules = keyword lists on the section path in FR and NL (e.g. `préhistoire|romaine|
   mérovingien|carolingien|voorgeschiedenis|Romeins` → ancient; `principautés médiévales|middeleeuwse vorstendommen`
   → medieval; `Bourgogne|Bourgondi` → burgundian; `Habsbourg|Habsburg|Pays-Bas espagnols|Spaanse|temps modernes|
   Moderne Tijdvak|principauté de Liège … époque moderne` → early-modern; `contemporaine|hedendaags|1789` →
   contemporary; part I → aux, part II → general). For V-Smart codes: `I.` → aux, `II.` → general, `III.A` → ancient,
   `III.B.1/2` → medieval, `III.B.3` → burgundian, `III.C` → early-modern, `III.D` → contemporary. Multi-valued.
   Report coverage per year (target ≥ 95 % of entries get ≥ 1 value).
2. **Places**: tags from the place indexes (1990–2007) + dictionary matching of the curated place list on title +
   section path for other years (whole-word, accent-insensitive). Synonym groups → `build/synonyms.json`.
3. **Journals**: normalisation key = lowercase, accents and punctuation removed, abbreviations expanded via the
   abbreviation list; group by key; canonical display = most frequent full form (prefer a form found in the ARA list).
   Facet "Journal" shows the top 300 canonical titles only. This key is for the facet. Identifying the same journal,
   the same publisher, or a similar entity is a later extension (the internal project plan, after the demo), as for persons.
4. **Language** of the title: a small local detector (`langid` or `lingua` with fr/nl/de/en/la/it/es); store code.
5. **Cross-references** resolved to ids (§3.1-7).
6. **PDF links**: A′ has pages already. For A, *stretch goal*: download the other decade PDFs (same site, 48–90 MB
   each, record in SOURCES.md), extract entry numbers per page from the text layer and map print numbers → PDF
   page. If not done, link to the decade PDF without a page.
7. **Similar publications**: embed `title + subtitle + title_translated + host title + section_path[-1]` with a
   local multilingual model via `sentence-transformers` (default `intfloat/multilingual-e5-base`; prefix `"passage: "`;
   fall back to `paraphrase-multilingual-MiniLM-L12-v2` if too slow), L2-normalise, brute-force top-10 cosine
   neighbours in chunks with numpy (≈175k × 768 fits in memory as float16), exclude self and cross-listing stubs.
   Cache embeddings in `build/embeddings.npy` keyed by record id + text hash. Spot-check 20 random records.

### P5 — Writers (1 week)
- `bhb export mods` → `build/mods/bhb-YYYY.xml` (`<modsCollection>`), validated against the MODS 3.8 XSD (download
  once into `pipeline/schemas/`). Mapping: `titleInfo/title|subTitle`, translated title as `titleInfo type="translated"`,
  `name type="personal"` with `namePart type="family|given"` and `role/roleTerm authority="marcrelator"` (aut, edt,
  com, trl, aui, ill), `originInfo` (place, publisher, `dateIssued`), `physicalDescription/extent`,
  `relatedItem type="host"` with the host subtitle, its editors, `part/detail[@type=volume|issue]` and `part/extent unit="pages"`,
  `relatedItem type="series"`, `note type="annotation"`, `classification authority="bhb"` per code,
  `subject/geographic` per place, `genre` = our `type`, `language/languageTerm`, `recordInfo` with
  `recordIdentifier source="bhb"`, `recordContentSource` (= "BGB-BHB YYYY, no. N, p. P" or "ARA V-Smart record N"),
  `recordOrigin` (parser + version), and `note type="printed citation"` holding `printed`.
- `bhb export sqlite` → `build/site-data/bhb.sqlite` + chunks + `config.json` for sql.js-httpvfs (§6.2). **Superseded (11 Oct 2026):** Pagefind replaced this export; there is no `bhb export sqlite` command.
- `bhb export flat` → `build/downloads/bhb.csv`, `bhb.ris`, `bhb.bib` (whole dataset, for the "Open data" page).
- **Done when:** MODS validates for all years; a round-trip import of `bhb-1975.xml` into Zotero works (manual check;
  ask Mike); SQLite passes the integrity check.

### P6 — Website (3 weeks) — see §6
- Visual identity is the Commission site, not a separate theme. Copy the header, the crest and the footer (§6.1).
### P7 — Deploy (1–2 days)
- `site/` builds to `site/dist/`. GitHub Action `deploy.yml`: on release published (or manual dispatch), download
  the release assets (`bhb.sqlite.*`, `config.json`, downloads) into `dist/data/`, build the site, deploy with
  `actions/upload-pages-artifact` + `actions/deploy-pages`. Data never committed.
- `bhb release vYYYY.MM.DD` (or a documented `gh release create …` command) uploads assets from `build/`.
- Beta URL: `https://<mike's-account>.github.io/<repo>/` — *ask* Mike for the repo name.

---

## 6. Prototype website requirements

### 6.1 Audience and tone
Historians of all ages (many senior, not tech-savvy) and students. The pages should look like a section of the
Commission’s own site, [https://commissionroyalehistoire.be/fr/](https://commissionroyalehistoire.be/fr/), measured on
11 Oct 2026. Header, banner and footer may be copied, including the logo. No animations beyond subtle transitions;
no dark patterns; no tracking cookies. There is no separate dark theme: the Commission site is a white page under
a green bar.

**Chrome to copy**

- Header crest: `https://commissionroyalehistoire.be/wp-content/uploads/2022/10/kcg_logo-rgb.svg` (left of the bar).
  Footer crest: `…/2022/10/kcg_logo-rgb2.svg`.
- Bar colour `#486249`. Menu: Proxima Nova Extra Condensed, uppercase, weight 500, 18px, letter-spacing ~0.9px.
  Current item `#F36F3A`; other items `#D7ECDD`. FR / NL / EN and a search icon on the right. Menu links go to the
  Commission site in the active language; the language switch changes this bibliography.
- Titles: Linotype Sabon, weight 400, `#F36F3A`. Body: Proxima Nova Condensed, 18px, `#303133`, on white.
  Pale panels and dropdowns `#EBF6EE`.
- Footer, as on the French home page: crest, name, Palais des Académies, Rue Ducale 1, B-1000 Bruxelles,
  +32 2 550 22 06, jeanluc.depaepe@gmail.com, “Avec le soutien de”, then the KVAB, ARB, BELSPO and Rijksarchief /
  Archives de l’État marks, the copyright line, Privacy Policy and the accessibility statement.

Use the same font families the Commission site already loads. A citation is set in Sabon, like their titles.

### 6.2 Data layer (SQLite)

**Superseded (11 Oct 2026).** The prototype search is Pagefind, not this SQLite layer. The measurement is in `docs/BENCHMARK.md`; the deployable site is in `docs/IMPLEMENTATION_PLAN.md`. The schema below is kept as the record of what was measured.
```sql
CREATE TABLE records (rowid INTEGER PRIMARY KEY, id TEXT UNIQUE, bgb_year INT, year INT, type TEXT, lang TEXT,
  source TEXT, display TEXT /* formatted citation HTML */, printed TEXT, json TEXT /* full record */);
CREATE VIRTUAL TABLE fts USING fts5(title, persons, host, notes, section, places, content='', 
  tokenize = "unicode61 remove_diacritics 2", prefix='2 3');   -- rowid = records.rowid
CREATE TABLE facets (rowid INTEGER PRIMARY KEY, year INT, bgb_year INT, type TEXT, lang TEXT, source TEXT);  -- keep narrow: dense pages = few range requests
CREATE TABLE facet_multi (rowid INT, facet TEXT, value TEXT);  -- period, journal, place, bhb_code
CREATE INDEX facet_multi_fv ON facet_multi(facet, value, rowid);
CREATE TABLE similar (rowid INT PRIMARY KEY, ids TEXT /* comma-separated rowids */);
CREATE TABLE synonyms (term TEXT PRIMARY KEY, group_terms TEXT);
CREATE TABLE stats (key TEXT PRIMARY KEY, value TEXT);  -- counts per year/source for the About page
```
Adjust after P1. Query expansion with `synonyms` happens client-side before building the FTS query.

### 6.3 Pages and behaviour

French, Dutch and English are equal. The header toggle (FR / NL / EN) switches every label and every documentation string, and nothing else: the query, the filters and the result list stay put. There is one search index for the whole bibliography, containing every language the records use, not one index per interface language. Before the query is sent, expand it with `synonyms.json` so a name in one language also matches its equivalents in the others. The citation on the page remains the printed text. Default language is the browser's, when it is `fr`, `nl` or `en`; otherwise French. The choice is remembered.

1. **Home** (`#/`): project name in the active language, one-line description, a single large search field with placeholder
   examples ("Gent 1830", "béguinages", "Leopold II Congo"), 4–6 example query chips, three key figures (entries,
   years covered, journals), "Browse by period" tiles (§5 P4 values). Language switch top-right. Beta banner.
2. **Results** (`#/search?q=…&period=…&y1=…&y2=…&type=…&lang=…&journal=…&sort=…&page=…`): the URL holds the full
   state (shareable, back button works).
   - Left column (collapsible on mobile): **Publication year** range (two inputs + a small histogram of hits per
     decade), **Period**, **Type**, **Language**, **Journal** (top 15 + "more…"), **Source** (print volumes /
     ARA database). Counts next to each value. Active filters as removable chips above the results.
   - Result list: 20 per page; each result = formatted citation (authors in small caps or bold, title, host in
     italics, year), a muted line with "BGB 1975 · no. 23701 · section name", and actions: **✦ Similar**,
     **Cite**, checkbox (select).
   - Sort: relevance (default with a query), year ↓, year ↑, author A–Z.
   - Empty-query search with only filters must work (browse mode).
   - "Advanced" toggle: fields for all words / exact phrase / any word / none of; author; title; journal; year range.
     The single box also accepts `author:`, `title:`, `journal:`, `year:1980-1990`, `"phrases"`, `-exclude`, `OR`.
3. **Record** (`#/record/bhb:1975-23701`): citation; **"As printed in BGB 1975, no. 23701"** box with the verbatim
   text and a link "View page in original volume (PDF)"; structured fields table (only fields present); section path
   as printed; cross-references as links; places; search-elsewhere links (KBR catalogue, WorldCat, Google Scholar
   with the title); **Similar publications** (up to 10); "Cite" (formats below); a "Report an error" link
   (`mailto:` to an address Mike provides: *ask*; prefilled subject with the id).
4. **✦ Similar** on a result opens an inline panel (or navigates to `#/similar/<id>`) listing the neighbours, with a
   one-line explanation "Publications with similar titles and subjects, computed automatically".
5. **Export**: "Export" button exports the selection, or, if nothing is selected, the whole result set up to 5,000
   rows (warn above that). Formats: **XLSX** (one row per record; columns: id, BGB year, number, authors, title,
   host, volume, issue, year, pages, publisher, place, type, language, period, section, printed citation, permalink),
   CSV (UTF-8 with BOM for Excel), RIS, BibTeX. Generate in the browser (SheetJS Community Edition from
   `cdn.sheetjs.com`, pinned version, or `write-excel-file`).
6. **Cite**: copy buttons for "BGB style" (as printed / display string), Chicago author-date and APA 7 (simple
   hand-written formatters from the record; no citeproc dependency needed).
7. **About** (`#/about`): what the bibliography is, the Commission, editors, **coverage table** (per BGB year: entries
   in this beta, source, completeness remark: "2009–2017: partial export from the ARA database; 2018 →: not yet
   included; full data in the ARA catalogue (link)"), methods (OCR by STRAIVE, parsing, automatic period facet and
   similarity), the CC BY-NC 4.0 attribution for the bibliography as a whole, how to cite the dataset, contact.
8. **Open data** (`#/data`): download links (MODS per year as zip, CSV, RIS, BibTeX), the same attribution, schema notes.
9. **Attribution on every page.** The footer (the copied Commission footer) also carries one line for the bibliography
   as a whole: the dataset title, the Commission, and CC BY-NC 4.0. The same credit is in every download (CSV header
   comment, RIS/BibTeX note, MODS `accessCondition`). There is no year or source under a different licence.

### 6.4 Design
- Fonts, colours, header, crest and footer are the Commission site’s, as measured in §6.1. WCAG AA contrast.
- Generous whitespace; max text width ≈ 75 characters for citations; visible focus states; keyboard operable
  (`/` focuses search, `Enter` searches, arrow keys in result list optional).
- Responsive down to 360 px width (filters in a drawer).
- All interface strings in `site/src/i18n/{fr,nl,en}.json`, one complete file per language; no hard-coded UI text
  and no missing key in only one language. Machine-assigned facets carry a small "auto" marker with a tooltip.

### 6.5 Performance and quality budgets
- Initial page load (home, cold) ≤ 300 KB JS+CSS gzipped, excluding the SQLite WASM worker (lazy-loaded on first
  search or on idle).
- Lighthouse (mobile): Performance ≥ 85, Accessibility ≥ 95, Best Practices ≥ 95.
- No console errors; works in current Chrome, Firefox, Safari (incl. iOS).

### 6.6 Honesty about the data
- Beta banner on every page: "Beta — coverage 1952–2008 from the printed volumes; 2009–2017 partial; 2018 and
  later not yet included" (adjust to what is actually included).
- Records parsed with low confidence show the printed citation only (no structured fields) and a small
  "automatically extracted" note.

---

## 7. Non-goals for the prototype (do not build)
Machine translation of titles; any LLM call; Zotero integration; MARC21/UNIMARC export; user accounts; server-side
code; author and
journal pages; a map of Belgium; analytics beyond none; editing data through the site. Looking a publication up on the web
to attach a link, a DOI or an abstract is a later extension (the internal project plan, after the demo), starting with the more
recent volumes, where a match is realistic. So is entity identification: clustering the same person, journal, publisher, series or corporate author
across entries and attaching an authority identifier. The prototype keeps each of those as printed. The P4
journal key is only a facet label. A later map of Belgium follows the list-and-map search used by sites
such as Airbnb: the map, with a grid drawn over it, and the facets restrict one shared result list
(the internal project plan, item 9).

---

## 8. Definition of done (prototype)

- [ ] `bhb build` (or a documented sequence of `bhb …` commands) regenerates everything from raw inputs in < 2 h on
      the Mac (embeddings may be cached).
- [ ] `build/ingest_report.md`: per-year counts by source; 1952–2007 complete except documented gaps; A′ included.
- [ ] Gold-standard scores reported (or the smoke test on 40 entries if the human pass has not happened yet).
- [ ] MODS for every year validates against the XSD.
- [ ] Site deployed on GitHub Pages; the P1 latency targets hold on the real data.
- [ ] All §6.3 pages work in NL, FR, EN; exports open correctly in Excel and import into Zotero (RIS).
- [ ] `pytest` green; `ruff` (or equivalent) clean; README instructions verified from a fresh clone.
- [ ] `docs/DECISIONS.md` lists every decision taken on your own, with one-line rationale.

---

## 9. Pitfalls (learned the hard way)
- The folder `Stage/Notebooks/Other_Gold_Standard ` ends with a **space**.
- `exports Rijksarchief/` contains a space; quote paths.
- `alle tss titels.csv` is **latin-1**, CRLF.
- STRAIVE XML has numeric entities (`&#x00E9;`) everywhere: always parse, never regex the raw XML for text.
- In STRAIVE files the same number series restarts (1959, 1993): print numbers are only unique *within* a year;
  hence ids include the BGB year.
- Persée OCR confuses Latin and Greek capitals (`Α`, `Β`), writes `V` for `l'`, `·` for `.`; the existing module
  normalises some of this; do not "correct" `printed` beyond whitespace/superscripts.
- Do not trust `<ref-list>` nesting or `publication-type`.
- GitHub rejects files > 100 MB and Pages sites > 1 GB; keep data out of git.
- `sql.js-httpvfs` needs the server to honour `Range`; GitHub Pages does (`206 Partial Content`), local dev servers
  may not: use `vite preview` or a range-capable static server for testing.

---

## 10. When in doubt
Prefer the simpler option that keeps the printed text visible and the pipeline reproducible. Record the choice in
`docs/DECISIONS.md`. Questions that truly need the product owner: repo/URL name, contact e-mail for error reports,
scheduling the human gold-standard pass, permission to download the other decade PDFs (stretch goal P4-6).
