# Proposal — a faceted, multi-label classification, linked to open vocabularies

Draft, 30 October 2026, for the product owner (Mike Kestemont) and the Royal Commission of History. It answers a wish
of the Commission: an entry should be able to carry more than one category, where the printed volumes allowed only
one. It keeps the ground rules: no LLM API, static site, the printed text unchanged, machine values flagged, confidence
floors. It builds on `docs/VOCABULARY_PROPOSAL.md` (open vocabularies per facet) and `docs/SEMANTIC_INDEX_PROPOSAL.md`
(meaning-based neighbours). Step F1 below is built; the rest is not.

## 1. What we do now

**The printed volumes (1952–2008)** place each entry once, under one heading of the volume's tree. A "Voir aussi /
Zie ook" line under another heading lists entries that also belong there; the pipeline keeps those as secondary
sections, but they are rare (201 entries).

**Three schemes in turn.** 1952–1992 use two older classifications; from 1993 the volumes, and the State Archives'
catalogue for 2009–2017 (V-Smart), use the modern BHB scheme: 220 codes in `data/curated/scheme.csv`.
`data/curated/heading_crosswalk.csv` maps the 2,581 older headings to modern codes; no person has reviewed it yet.

**The catalogue already gives several codes.** In V-Smart, 5,253 records (11 %) have more than one BHB code. The
editors wanted multiple labels already; print could not show them.

**A code is a combination of facets.** Each modern code packs a period and a subject area, sometimes a region, into
one slot:

| Code | Period | Subject area |
|---|---|---|
| III.C.1.b | Early modern: Spanish and Austrian Netherlands | central institutions, estates, law |
| III.D.2.a | Contemporary, 1789 to today | institutions and politics |
| III.D.2.e | Contemporary, 1789 to today | culture |

The same subject has a different letter in each period (institutions are *b* under III.C, *a* under III.D). This is an
*enumerative* scheme: every combination is made in advance, and an entry gets one slot.

**The site already splits codes into two facets.** The pipeline derives a **period** (7 values, `bhb/facets.py`) and a
**theme** (8 values, `data/curated/theme_map.csv`) from each code and each printed heading. Both are multi-valued:

| Facet | Entries with a value (of 181,893) | Entries with more than one value |
|---|---:|---:|
| Period | 172,736 (95.0 %) | 3,085 |
| Theme | 113,268 (62.3 %) | 17,513 |

Themes are missing mostly before 1993 (14–36 % of entries per year), because the older headings are not yet mapped.

## 2. The proposal: facets first, codes as the source

Describe each entry along separate facets, each with as many values as the entry needs:

| Facet | Values now | Finer level later |
|---|---|---|
| **Period** | 5 periods: antiquity, Middle Ages, Burgundian, early modern, contemporary | about 17 periods the scheme names (the French period, 1914–1918, federal Belgium …), with dates |
| **Subject area** | 8 themes, including *reference* and *general works* | the 137 subject wordings of the scheme (Protestantism, demography …) as narrower concepts |
| **Place** | none yet | communes, regions and historical territories, from the printed place indexes (1990–2007) |

Principles:
- **Multiple values are normal.** A study of 1780–1830 has two periods; an article on beguines in Ghent has *religious*
  and *social*, and the place *Ghent*. No pair of codes is needed to say that.
- **The BHB codes stay, as the source.** A printed heading or a V-Smart code is the most reliable way to fill the facets,
  and the pipeline already does so. No entry loses its code; the code is shown on the record page as printed.
- **Two values are not periods.** "Auxiliary sciences" and "general" are parts of the bibliography, not periods. They
  belong to the subject facet (*reference*, *general works*, which exist already); an entry across all periods simply has
  no period. The site keeps them in the period filter until the Commission decides (step F2).
- **Every value says where it comes from**: the printed volume, the catalogue, a person, or the machine. Machine values
  are shown as "suggested".

## 3. How entries get their values

1. **From the source, as now.** Code → period and subject area; printed heading → code through the crosswalk; "Voir
   aussi" → an extra value.
2. **Machine suggestions per facet.** For an entry, look at its closest neighbours in meaning that already have values
   (the bge-m3 vectors behind similar publications), and suggest the values most of them share. One prediction per
   facet, so a few classes with many examples each, instead of 220 codes with few examples. A value is stored only
   above the threshold that gives **at least 90 % precision** on held-out years (V-Smart 2015–2017, print 2005–2008).
   Below it, nothing is stored. This is step S0b of the semantic-index proposal, done per facet.
3. **People check samples.** The held-out years are modern, so they overstate accuracy before 1993. A sample of 100
   pre-1993 entries is checked by the editor or by students before machine values for those years are shown.

## 4. Linked to SKOS and open vocabularies

**Built (30 October).** `bhb export skos` writes `build/skos/bhb.ttl` from the curated files:
- three SKOS concept schemes: the BHB codes (220), the periods (7) and the subject areas (8), with French, Dutch and
  English labels; the English labels of the codes carry a note that they are drafts;
- each code has its parent (`skos:broader`) and a `skos:broadMatch` to every period and subject area it implies:
  418 such links. III.D.2.a is narrower than *contemporary* and narrower than *institutions and politics*. That is the
  decomposition of §1, in a standard form any SKOS tool can read;
- no link from a code to "auxiliary sciences" or "general" as a period (§2).

The facet values themselves are in one curated file, `data/curated/facets.csv`. The file validates with rdflib
(2,182 triples, no broken parent links). The URIs are planned under
`https://mikekestemont.github.io/bebibhist/vocab/`; they are not served yet.

**Next.** The facet values get links to open vocabularies, as `docs/VOCABULARY_PROPOSAL.md` sets out: periods to
PeriodO and Wikidata (and the BHB periodisation submitted to PeriodO as its own authority), subject areas to Wikidata
and FAST, places to Wikidata and GeoNames. The links go into one curated file and into `bhb.ttl` as
`skos:closeMatch` or `skos:exactMatch`. Because every code already points to its facet values, a link added to a value
reaches every code and every entry under it. Nothing has to be labelled again.

## 5. What readers see

- The period, subject and (later) place filters accept several values per entry; an entry appears under each.
- The record page lists all values of each facet, the printed heading as it stands, and marks machine values as
  "suggested", with how they were obtained.
- MODS exports carry each value with its URI (`authorityURI`, `valueURI`).
- Search by meaning (the "Related by meaning" trial, 30 October) complements the facets: it finds a subject that no
  facet value names.

## 6. Steps and stop points

| Step | Effort | Stop point |
|---|---|---|
| F1 facet values file, `bhb export skos` with code → facet links | done 30 Oct | — |
| F2 move "auxiliary sciences" and "general" out of the period facet | ½ day | **Commission's go** (§7) |
| F3 machine suggestions per facet (S0b), with precision and coverage per year | 1 day | **report** before anything is shown |
| F4 finer periods (about 17, with dates) and subject wordings (137) as narrower concepts | 1 day + the editor's review of dates | editor's review |
| F5 links to PeriodO, Wikidata, FAST (VOCABULARY_PROPOSAL V2–V4) | 2–3 days + checking | sample check |
| F6 serve `bhb.ttl` and a page per concept on the site; URIs in MODS | 1 day | deploy |
| F7 place facet, from the printed place indexes | 3–5 days + review | outside this phase |

## 7. Questions for the Commission (9 November)

- Should the facets (period, subject, place) become the main way to classify, with the BHB codes kept as the source?
- May machine-suggested values be shown, marked as such, once they reach 90 % precision on the checked years?
- Should "auxiliary sciences" and "general" leave the period filter?
- Is a finer periodisation wanted, and who decides the dates the scheme does not print?
- May the BHB periodisation be published in PeriodO under the bibliography's name?
- Must the English labels be reviewed before the vocabulary is published?
