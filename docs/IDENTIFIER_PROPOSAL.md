# Proposal — DOIs, ISBNs and ISSNs for every entry

Draft, 30 October 2026, for the product owner (Mike Kestemont). Nothing in this file is built yet. It answers one
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
| E0 pilot: 1,000 entries, stratified by decade and type, through E1–E3 | 1–2 days | **report**: coverage per stratum, precision on a hand-checked sample, run time |
| E1 journals and ISSNs | 2 days + review of the large clusters | review list for the editor or students |
| E2–E3 all entries | 2 days of work, about 1–2 days of run time | report as in E0, then a data release |
| E6 site: links, open copies, exports | 1 day | deploy |
| Abstracts in search | ½ day | decision on showing them |

## 8. Open questions

- Whether students can check the review lists (Sébastien's suggestion for labelling applies here too).
- Whether the Commission wants an "Open copy" link to repositories it does not control.
- Whether abstracts may be shown, after the terms are checked.
