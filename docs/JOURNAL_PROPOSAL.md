# Proposal — one name per journal

Draft, 31 October 2026, for the product owner (Mike Kestemont). Measured on `build/records.jsonl`; nothing is built
yet. It keeps the ground rules: `printed` and the journal name as printed never change; a journal identity is a
value next to them, flagged with how it was found.

## 1. Where we stand

102,957 articles name their journal, in **19,503 spellings** (15,614 after folding case, accents and punctuation;
9,924 of those occur once). The catalogue years (2009–2017) use 966 spellings, almost one per journal; the printed
volumes use 18,148, because each volume abbreviated in its own way: *Revue belge de philologie et d'histoire* is
written 17 ways, from "R.B.P.H." to "Belgisch tijdschrift voor filologie en geschiedenis". The 1,000 most frequent
spellings cover 68 % of the articles. Most of the top is local and regional periodicals (*Biekorf*, *Eigen Schoon en
De Brabander*, *Het Land van Aalst*, *De Leiegouw*, *Wavriensia*).

Two parser gaps show up in the list: **"Ibid."** is the journal of 1,685 entries (it means "the journal of the
previous entry"), and a few spellings hold a volume number ("Biekorf 57").

## 2. What can be settled without a person

| Step | Spellings | Articles covered (cumulative) |
|---|---:|---:|
| ISSN anchors: a spelling whose articles matched Crossref or VABB with one ISSN (567 journals) | 801 | 11 % |
| Frequent spellings written out in full (≥ 15 articles, no abbreviation dots): one journal each | 745 | |
| Abbreviations that fit exactly one of those: every abbreviated word is the start of a word of the full title, in order, covering most of it ("Bull. du C. Art et H. de Gembloux") | 990 | **66 %** |
| "Ibid." resolved to the journal of the previous entry in the same volume | (1,186 of 1,685 entries) | + 1 % |

A sample of 30 abbreviation links was right throughout. 228 abbreviations fit several journals and stay open.

The written-out names themselves still contain variants: in 122 pairs one name is the other plus a place, subtitle
or volume ("Biekorf" / "Biekorf (Brugge)", "Het Land van Aalst" / "… (Aalst)"). Merging those leaves about 1,200
journals for two thirds of the articles.

## 3. Method

J1. **Clean the spellings first.** Resolve "Ibid." to the previous entry's journal (flag `ibid-resolved`; where the
previous entry is itself unclear, leave it); strip a trailing volume number or place in brackets for comparison only.

J2. **Anchors.** Spellings with an ISSN from Crossref or VABB; print and online ISSNs of one journal are joined.
Generic words ("Handelingen", "Bulletin", "Annales", "Revue") never anchor a journal by themselves: they occur in
dozens of titles.

J3. **Journal list.** One row per journal in `data/curated/journals.csv`: an id, the full title, the ISSNs, later
the Wikidata item, and the predecessor and successor titles where a journal was renamed (the *Annales de la Société
d'Émulation* became the *Handelingen van het Genootschap voor Geschiedenis*). A second file maps each spelling to its
journal, with how it was found (`issn`, `abbreviation`, `variant`, `person`).

J4. **Review, by weight.** A person checks the journal list from the largest down (the 200 largest journals cover
more than a third of the articles) and the 228 ambiguous abbreviations. Spellings used once or twice are not
reviewed one by one; they stay as printed until a rule or the citation clean-up pass links them.

J5. **The rest (a third of the articles).** Rare abbreviations and OCR-damaged names. The citation clean-up pass
(decision of 31 October) can propose the full title of an abbreviated journal as a separate field, checked against
the journal list; Wikidata and the ISSN anchors of later years help for journals that continue.

## 4. What readers get

- **A journal filter and a journal page**: every article of a journal, whatever the spelling, by year.
- The citation stays as printed; the record page adds the journal's full title and ISSN.
- Exports carry the full title and ISSN (`<relatedItem type="host">` with `<identifier type="issn">` in MODS).
- It feeds back into matching: an ISSN in a Crossref query makes DOIs more certain and more numerous.

## 5. Steps and stop points

| Step | Effort | Stop point |
|---|---|---|
| J1 Ibid., volume numbers in names | ½ day | count, sample |
| J2–J3 anchors, abbreviations, variants → `journals.csv` and the spelling map | 1–2 days | **review list** for Mike: the largest journals and the ambiguous abbreviations |
| J4 review | Mike's time, by weight | — |
| Site: journal filter, journal page, full title and ISSN on the record | 1 day | deploy |
| J5 the rest, with the citation pass | with that pass | sample check |
