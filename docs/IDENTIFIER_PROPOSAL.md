# Proposal — DOIs, ISBNs and ISSNs for every entry

Draft, 30 October 2026, for the product owner (Mike Kestemont). The pilot (E0, Crossref only) ran on 31 October; its
result is in §5b. Nothing is shown on the site yet. It answers one
request: a later, thorough clean-up that finds a persistent identifier for as many entries as possible, and the links,
open full texts and abstracts that come with them. It keeps the ground rules: no LLM API, static site, the printed text
unchanged, machine values flagged, confidence floors.

## 1. Where we stand

On `build/records.jsonl` (30 Oct, after the volume split), 181,893 entries are searchable:

| Part | Entries | Articles | Books | Chapters | Other |
|---|---:|---:|---:|---:|---:|
| Print 1952–1992 | 71,402 | 43,790 | 11,341 | 4,711 | 11,560 |
| Print 1993–2008 | 64,595 | 31,327 | 12,349 | 14,012 | 6,907 |
| V-Smart 2009–2017 | 45,896 | 28,236 | 7,338 | 10,322 | 0 |

There are no DOIs, 4 ISBNs, no ISSNs and 71 web links. Article hosts are written in 17,012 different ways
(abbreviations such as "Bull. du C. Art et H. de Gembloux"); the number of real journals is much smaller, but unknown.

## 2. What an identifier gives

- **A link to the publication.** A DOI resolves to the publisher's page through `https://doi.org/…`. An ISBN gives a
  search link to a library catalogue (KBR, Open Library). An ISSN gives the journal's record and its other issues.
- **A free legal copy, when there is one.** OpenAlex and Unpaywall report an open-access URL per DOI (Persée, institutional
  repositories). This is the most useful gain for readers.
- **Abstracts, for some entries.** Crossref holds abstracts that publishers chose to deposit, and OpenAlex holds abstracts
  for part of its works. Both are a minority, and mostly recent international journals. Abstracts belong to their authors
  or publishers, not to the bibliography: they can feed search, themes and similar publications at build time without
  being shown, and showing them needs a separate decision (§6).
- **Better data.** A journal identifier settles the 17,012 host spellings (the journal identification planned for phase 3).
  Matched metadata catches OCR errors in titles (Jeroen's `Seivias → Scivias`), without touching `printed`. Duplicates
  across years become visible.

## 3. Sources (open, no LLM)

| Identifier | Source | Notes |
|---|---|---|
| DOI | **Crossref** REST API | Free; the "polite" pool asks for a contact address. Bibliographic query by title, author, year, ISSN. |
| DOI, ISSN, open-access URL, abstract | **OpenAlex** API | CC0 metadata. Journals ("sources") carry their ISSNs. |
| DOI | **Persée** | Digitised French-language journals, including the *Revue belge de philologie et d'histoire*; DOIs under `10.3406`. Likely the best source for older Belgian articles. |
| ISSN | OpenAlex sources, **Wikidata**, ROAD | The full ISSN Portal is paid; these free sources should cover most scholarly journals. Local periodicals may have none. |
| DOI, ISBN, ISSN | **VABB-SHW** (ECOOM, open data on Zenodo, CC BY 4.0) | The Flemish Academic Bibliography for the Social Sciences and Humanities: publications by researchers at Flemish universities, with DOI, ISBN and ISSN. Editions VIII (2000–2017, 81,122 publications), IX (2008–2017) and 15 (2014–2023) are downloaded to `build/external/`. Local, so it covers Flemish journals and books that Crossref lacks; it has no francophone or pre-2000 publications. |
| ISBN | **Open Library**, national library catalogues (SRU) | ISBNs exist from about 1970. KBR, DNB and the Library of Congress are to be checked for open access and terms. WorldCat needs a licence. |

The terms of each service are checked before the first run, and the requests are throttled to what each asks.

## 4. Method

E1. **Journals first.** Cluster the 17,012 host spellings into journals (accent-folded, abbreviations expanded,
compared with `rapidfuzz`), then match each cluster to an ISSN and an OpenAlex source id. A journal match is reviewed by
hand when it covers many entries; this list is short compared with the entries.

E2. **Articles → DOI.** Query Crossref and OpenAlex with the title, the first author's family name, the year, and the ISSN
when E1 found one. A candidate is scored on title similarity, author, year (±1), volume and first page.

E3. **Books → ISBN; chapters → DOI or the book's ISBN.** Query by title, author or editor, year and place. Publishers such
as Brepols, Brill and Leuven University Press give chapters their own DOIs; other chapters take the ISBN of their volume
(the split of 30 Oct links them to it).

E4. **Acceptance.** Store an identifier only above a score floor, set from a hand-checked sample so that **at least 98 %
of stored identifiers are right**. A wrong link is worse than none. Below the floor, nothing is stored. Between the floor
and a lower bound, the candidate goes to a review list. Every stored value is flagged as machine-derived
(`doi-matched`, `isbn-matched`, `issn-matched`) with its score. `printed` is never changed.

E5. **Cache and resume.** Every response is cached on disk (`build/cache/`), so a run can stop and continue, and a rebuild
does not query again. Matching is a `bhb` command, run on the laptop like `bhb similar`; its result goes into the data
release, not into the Pages workflow.

## 5. Coverage to expect

No reliable estimate can be given before a pilot. Expect high coverage for V-Smart articles in international journals,
moderate coverage for 1993–2008, and low coverage before 1990 and for local history periodicals (heemkundige kringen,
cercles d'histoire), which rarely registered DOIs. Persée may lift the older French-language journals.

## 5b. Pilot result (31 October 2026)

`bhb identifiers pilot` (`bhb/identifiers.py`) queried Crossref for 1,000 recent entries: 500 articles and chapters of
the 2007 volume and 500 of the State Archives' catalogue (2016–2017), one query each (title, first author, journal or
volume, year ±1), cached in `build/cache/crossref/`. The run took about six minutes. The candidates are in
`build/identifiers/pilot.csv`.

| Part | Entries | With a DOI |
|---|---:|---:|
| Print 2007, articles | 308 | 39 (13 %) |
| Print 2007, chapters | 192 | 6 (3 %) |
| Catalogue 2016–2017, articles | 386 | 28 (7 %) |
| Catalogue 2016–2017, chapters | 114 | 26 (23 %) |
| **All** | 1,000 | **99 (10 %)** |

**Acceptance rule.** The title must be the same (similarity ≥ 95) or close enough for an OCR error (≥ 85, then three
other fields must agree); the author and the year (±1) must not disagree; at least two of author, year, journal and
first page must agree; a title shorter than 30 characters ("Belgium") also needs the journal or the first page. A
different journal name does not reject a candidate, since Crossref often gives the series or an abbreviation (BMGN, WT)
where we have the full title.

**Precision.** All 99 accepted DOIs were checked by hand against title, journal and author: all are right. With 99 checks,
this shows precision is very likely above 96 %, not yet that it is above the 98 % of E4; a larger check comes with the
full run.

**Coverage** follows the journals: the *Revue belge de philologie et d'histoire* and the *Bulletin* of the Commission
(Persée), *Le Moyen Âge*, *Revue du Nord*, *BMGN*, *WT*, *Brood & Rozen*, *Handelingen* of several Ghent societies
(`10.21825`, Ghent University's journal platform), Brepols and Brill volumes, international journals. Local periodicals
mostly have no DOI.

**OCR in titles.** In 8 of the 99 matches one word differs. Our title is wrong in four or five (`terrrein`, `7474`,
`infirme` for `infime`, `literacy` for `literary`), Crossref's in others (`eonversacio`, an OCR error at Persée), and
some are spelling variants (`voiage`). A matched title is therefore a **proposal** for correction, to be reviewed; it
never replaces our title or `printed` automatically.

**Run time for everything.** About 100,000 articles and chapters at this pace take roughly ten hours, once.

## 5c. VABB-SHW (31 October 2026)

An exact match on title and publication year (±1) finds 2,605 of our entries from 2000 on in one of the three VABB
editions (4 %): 1,619 articles, 698 chapters, 268 books. What it adds is mostly what Crossref lacks: **ISSNs** for
1,553 articles (journal identification, step E1) and **ISBNs** for 645 chapters and 229 books; DOIs for only 239.
A fuzzy match, as for Crossref, will find more (OCR errors, subtitles). VABB also gives normalised names of Flemish
authors, which may help to tell namesakes apart later. Credit: ECOOM, VABB-SHW editions VIII, IX and 15 (CC BY 4.0).

## 6. Site

- A "DOI" link and, when OpenAlex reports one, an "Open copy" link on the record page and in the expanded row.
- ISBN and ISSN as fields, each with a catalogue search link.
- Exports (BibTeX, RIS, MODS) carry the identifiers; MODS as `<identifier type="doi">` and so on.
- Abstracts are **not shown** in the first version. They may feed search and similar publications at build time. Showing
  them is decided after checking the terms of the sources (Crossref and OpenAlex pass on publisher abstracts; the
  copyright stays with the rights holder, and our data licence is CC BY-NC).

## 7. Effort and stop points

The matching runs locally against free APIs, without an LLM, so its cost is run time, not tokens. At a few requests per
second, 180,000 queries take roughly a day of unattended run time per source; the cache makes later runs fast.
Writing and checking the code is a few days of work.

| Step | Effort | Stop point |
|---|---|---|
| E0 pilot: 1,000 recent entries, Crossref — **done 31 Oct, §5b** | 1–2 days | **report**: coverage per stratum, precision on a hand-checked sample, run time |
| E1 journals and ISSNs | 2 days + review of the large clusters | review list for the editor or students |
| E2–E3 all entries | 2 days of work, about 1–2 days of run time | report as in E0, then a data release |
| E6 site: links, open copies, exports | 1 day | deploy |
| Abstracts in search | ½ day | decision on showing them |

## 8. Open questions

- Whether students can check the review lists (Sébastien's suggestion for labelling applies here too).
- Whether the Commission wants an "Open copy" link to repositories it does not control.
- Whether abstracts may be shown, after the terms are checked.
