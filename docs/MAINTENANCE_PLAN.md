# Maintenance plan — phase 3: master files and yearly releases

Version 0.1 — 10 November 2026. Product owner: Mike Kestemont. Status: **proposal, not started.** Phase 2
(`docs/IMPLEMENTATION_PLAN.md`) stays the current task until the freeze of §2; this plan then replaces its release
chain.

---

## 1. Why

Today every build starts again from the raw deliveries and replays all fixes on top of them: the hand corrections
(`data/curated/corrections.csv`), the machine OCR corrections (`ocr_persee.csv`, `ocr_names.csv`), the field repairs
(`bhb/repair.py`), the heading crosswalk, the citation pass, the id rewriting when a printed number is repaired, and
the release chain of `pipeline/README.md`. That was right while the parser and the citation pass were still
improving, but it is the wrong shape for maintenance. A one-word correction from a reader needs a rule, a row in a
correction file and a rebuild of several hours. And each new layer must be applied in the right order with the others
(on 6 Nov the citation pass undid 228 of 236 name corrections, because it read the text before them).

The yearly rhythm from 2027 on:

- **Three or four minor updates a year**, before the Commission's meetings: corrections that readers send in by
  email, and small fixes found along the way.
- **One larger update a year**, at the end or start of the calendar year: the new titles collected in Zotero
  (§5), plus refreshed links and identifiers.
- **One deposit a year on Zenodo**, as a new version of one record with a DOI that does not change (§6).

For that, the records themselves should become the source: **master files** that are corrected in place, with git
history as the record of every change, instead of the raw deliveries plus a growing stack of fixes.

## 2. The freeze

The change is made once: the current pipeline runs for the last time, and its output becomes the master.

- **What is lost.** After the freeze, a better parser or a new citation pass can no longer be rerun over the raw
  text. That is why the freeze waits until the extraction is good enough. From then on a systematic fix (like the
  129 headings of 10 Nov, or the i-read-as-l errors) is a script that is run once against the master, and its diff
  is committed. Scripts are kept in `pipeline/bhb/migrations/`, dated, for the record, and are never run again.
- **What is retired.** `corrections.csv`, `ocr_persee.csv`, `ocr_names.csv`, the repair rules, the heading
  crosswalk's application step and the id rewriting (`bhb/ids.py`) are applied for the last time and then frozen:
  they stay in this repository's history, with the commit that made the master. A correction's note (its source,
  why it was made) moves into the record (§3.4).
- **When.** Proposed: after the next big run on the new V-Smart export and the translation fix of
  `IMPLEMENTATION_PLAN.md` §4h, ideally before the Commission's Christmas meeting. If the export has not come by
  mid-January 2027, the printed volumes are frozen anyway, and the V-Smart years enter the master later as a one-off
  intake through the current pipeline (open question 1).
- **Page in the volume.** The master should say where each entry was printed: volume, entry number and page. Only
  2,637 of 183,578 records know their page today (`pdf.print_page`). At the freeze, a one-off job looks up each
  entry's printed number in the PDF of its volume to fill the page. Whether the PDFs' text layers allow this is
  not yet tested.

## 3. The master: MODS 3.8

### 3.1 Why MODS

The master follows a library standard, so that others can read it without our documentation, it is checked
against a published schema, and its form does not drift with each change to our code. The candidates:

| Standard | Verdict |
|---|---|
| MARC 21 / MARCXML | The catalogue standard, but numbered field codes (`100 $a`) are hard to edit and review, and articles inside journals fit it poorly. Given as an export (§6). |
| BIBFRAME (linked data) | Too heavy for a project this size; almost no tool edits it directly. |
| Dublin Core | Too thin: no structured host, volume or pages, so articles and chapters lose their place. |
| CSL-JSON | Made for formatting citations: no classification, no provenance, no record management. Given as an export. |
| **MODS 3.8** (Library of Congress) | **Chosen.** Rich enough for everything the record holds, readable XML, and `bhb export mods` already writes it. |

MODS covers the record almost entirely: a chapter's book, an article's journal and a book's series are each a
nested `relatedItem` (`host`, `series`); roles use the MARC relator codes (`aut`, `edt`, `com`, `trl`, `ill`, and
`aui` for the author of a preface or introduction); the BHB code is a `classification` with `authority="bhb"`;
identifiers (DOI, ISBN, ISSN, the KBR record) are `identifier` elements; and `recordInfo` holds the id, former ids,
dates and notes on the record's history (`recordInfoNote`, new in MODS 3.7).

### 3.2 Layout

- **Its own repository**, `bebibhist-data` (name to be confirmed): the data are CC BY-NC-SA 4.0 and the code
  MIT, this repository must not hold large data (`AGENTS.md`), and the data's history stays readable apart from
  the code's. The pipeline finds it beside this repository, or in the folder named by `BHB_MASTER`, as it finds the
  raw inputs through `BHB_RAW`.
- **One file per printed volume** (`mods/bgb-1952.xml` …), one per V-Smart year, and one per Zotero intake year
  (`mods/zotero-2027.xml`); each a `modsCollection`, records sorted by id.
- **Size.** The current export takes about 2.2 KB per record (measured on 2,040 records): about 400 MB in all, or
  7 MB per volume on average, a little more with §3.3. Within the 20 MB per file of `AGENTS.md`; git stores XML
  compressed.
- **One canonical form**, written by `bhb master fmt`: fixed element and attribute order, two-space indent, one
  element per line, text in Unicode NFC, empty elements left out. Every tool that writes the master writes this
  form, so a one-word correction is a one-line diff.

### 3.3 The record

```xml
<mods ID="bhb-1952-2732">
  <titleInfo><title>Bibliographie de l’histoire de Belgique 1951</title></titleInfo>
  <name type="personal">
    <namePart type="family">Scufflaire</namePart>
    <namePart type="given">A.</namePart>
    <role><roleTerm authority="marcrelator" type="code">aut</roleTerm></role>
  </name>
  <genre authority="bhb">article</genre>
  <relatedItem type="host">
    <titleInfo><title>R. du Nord</title></titleInfo>
    <part>
      <detail type="volume"><number>XXXIV</number></detail>
      <extent unit="pages"><list>133–64 et p. 227–59</list></extent>
    </part>
  </relatedItem>
  <classification authority="bhb">II.B.</classification>
  <relatedItem type="isReferencedBy" displayLabel="Listed in">
    <titleInfo><title>Bibliographie de l’histoire de Belgique 1952</title></titleInfo>
    <part>
      <detail type="entry"><number>2732</number></detail>
      <extent unit="pages"><start>…</start></extent>
    </part>
    <classification authority="bhb-printed">Généralités / A. Instruments bibliographiques généraux</classification>
    <note type="printed citation">Dhondt (J.), …, Soufflaire (A.). Bibliographie … p. 227–59.</note>
  </relatedItem>
  <recordInfo>
    <recordIdentifier source="bhb">bhb:1952-2732</recordIdentifier>
    <recordInfoNote type="correction">2026-11-06: family name read Soufflaire (OCR); corrected by rule.</recordInfoNote>
  </recordInfo>
  <extension>
    <bhb:machine field="persons" from="ocr-names"/>
    <bhb:machine field="classification" from="classifier"/>
  </extension>
</mods>
```

- **The printed listing is a relation.** Everything about where the entry was printed (volume, entry number, page,
  the printed heading and the printed citation) lives in an `isReferencedBy` relation to the volume. A publication
  listed in two volumes is then one record with two such relations, instead of two records linked by
  `duplicate_of`; the second id stays valid as a former id.
- **The printed citation is frozen.** It is the text as digitised, with the OCR corrections made up to the freeze,
  and nobody edits it afterwards: after the freeze every correction goes to the fields. It stays because it is the
  evidence for judging a reported error. The site already builds its catalogue line from the fields; the printed
  line stays on the record page as the text of the volume.
- **Machine-derived values stay marked** (`AGENTS.md`). MODS has no attribute for that, so a small BHB extension
  (its own namespace, with a schema of its own) lists per record the fields a machine set, and from what: the
  citation pass, the classifier, Crossref, VABB-SHW, KBR, ORCID, the OCR rules. When a person checks a field, its
  `bhb:machine` line goes.
- **Ids are frozen.** `bhb:<year>-<number>` stays as it is (in the `ID` attribute written `bhb-…`, since an XML id
  cannot hold a colon), and is never renumbered again. A record merged into another keeps its id as a former id
  (`recordIdentifier source="bhb-former"`); a removed record stays as a withdrawn stub, so that every permalink
  keeps working (`IMPLEMENTATION_PLAN.md` §4d). New titles get ids from a counter: `bhb:z2027-0001` ….

### 3.4 What stays out of the master

Everything a machine derives again at each release, and nobody corrects by hand: the title translations (for search
only), similar publications, the topic map, open-access status, the citation pass's search-only OCR variants, and
the suggested periods, subject areas, places and languages. They are rebuilt from their caches into `build/` after
the master is read, keyed by id. A suggestion that a person confirms moves into the master.

## 4. Correcting the master

A reader's report becomes a commit in the data repository:

1. **Find.** `bhb master find <words>` searches the master and prints each match's id, file, line, the printed
   listing and its site link.
2. **Edit in place**, the field itself, with a `recordInfoNote type="correction"` saying what was wrong, when, and
   on whose report (a reader is named only with their consent; open question 3).
3. **Check.** `bhb master fmt --check` and `bhb master check`: the MODS 3.8 schema and the extension's schema; every
   id and former id unique; every host and relation pointing at a record that exists; every code in
   `data/curated/scheme.csv`; years in range; every person with a family name. The same checks run in the data
   repository's CI on every push.
4. **Commit**, one commit per report, its message naming the report and the records changed.

A fix that touches many records is a migration script (§2), reviewed through its diff like any other commit.

The site build then reads the master into the pipeline's `Record` model (a MODS reader, the reverse of
`bhb/mods.py`), adds the derived layers of §3.4, and builds the index as now. A minor update needs no LLM pass and
no rebuild from the raw inputs.

## 5. New titles from Zotero

- **Entry.** New titles are entered in a dedicated collection of a Zotero group library owned by the Commission
  (open question 4). A short entry guide fixes the item types, which creator role to use for editors, translators
  and the writers of a preface, the language field, and one tag per BHB code (`BHB II.B.`), so that each title is
  classified as it is entered.
- **Import.** Once a year, `bhb intake zotero` reads the collection through the Zotero web API (the key in
  `ZOTERO_API_KEY`, never in a repository). The API can return MODS itself (`format=mods`); the importer starts
  from that and adds the BHB id, the code from the tag, the Zotero key (`recordIdentifier source="zotero"`, so an
  item is never imported twice) and the extension.
- **Checks before merging.** Each new title is matched against the master for duplicates (identifiers first, then
  title, author and year), and against Crossref, VABB-SHW and KBR for identifiers, as the printed entries were; its
  title is translated for search through the pass of `IMPLEMENTATION_PLAN.md` §5c. The importer writes a review
  report; the titles are merged once it is read.
- **After the import the master wins.** A later edit to an imported item in Zotero is listed in the next intake's
  report as a difference to look at, never applied by itself.

## 6. Releases

- **Minor update** (three or four a year): the corrections since the last one, a git tag in the data repository
  (`2027.1`, `2027.2` …), and the site rebuilt from the master. No Zenodo deposit.
- **Annual release** (`2027.0`, in January): the Zotero intake, the links and identifiers refreshed for the new
  titles (DOIs, ISBNs, ORCID iDs, KBR), the derived layers rebuilt, a GitHub release in the data repository, and a
  new version of the Zenodo record.
- **Changes list.** Each tag gets `CHANGES.csv` (id, field, old value, new value, reason), generated from the diff
  since the previous tag, for readers who do not use git.
- **The Zenodo deposit** holds the MODS files (the master itself), the extension's schema, the changes list since
  the previous deposit, a README with the licence (CC BY-NC-SA 4.0) and how to cite, and exports made from the
  master: MARCXML for library catalogues (with the Library of Congress's MODS-to-MARC stylesheet), CSL-JSON and RIS
  for reference managers, and the JSON Lines the site reads. Zenodo's GitHub integration is made to archive the
  repository's own files, not exports built at release time, so the deposit is made with Zenodo's API instead
  (`bhb release zenodo`, the token in `ZENODO_TOKEN`), as a new version of one concept record holding exactly
  these files.

## 7. Work

| Step | Effort |
|---|---|
| Extend `bhb/mods.py` into a full writer and add a reader, so that every master field goes to MODS and back unchanged; test the round trip on all records | 2–3 days |
| Test the page lookup in the volume PDFs; run it if it works | ½–1 day |
| `bhb master fmt`, `bhb master check`, the extension's schema, CI in the data repository | 1 day |
| The freeze: last run, conversion, data repository, site build from the master, retire the correction files | 1 day |
| `bhb master find` and the correction routine of §4 | ½ day |
| `bhb intake zotero`, the review report, the entry guide | 2 days |
| Changes list, exports, `bhb release zenodo` | 2 days |

## 8. Open questions (Mike)

1. Freeze before the Christmas meeting, with or without the new V-Smart export?
2. The data repository's name and owner (Mike's account, or an organisation for the Commission).
3. May readers who report errors be named in the records, or only "a reader's report"?
4. Who owns the Zotero group library, so that it outlasts any one person's account?
5. Should the minor updates go to Zenodo as well, or only the annual release (as proposed)?
