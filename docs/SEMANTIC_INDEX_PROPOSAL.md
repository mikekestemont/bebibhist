# Proposal — a semantic index for search, themes and similar publications

Draft, 25 October 2026, for the product owner (Mike Kestemont). Nothing in this file is built yet. It answers two requests: (1) the
theme gap should be closed by automatic semantic indexing before the editor reviews the crosswalk row by row; (2)
"Similar publications" (plan E8, deferred) should be built on that same index. It keeps the ground rules: static
site, no server, no LLM API, local open models only, machine values flagged, confidence floors.

## 1. Why

- **Themes.** In `build/classification_report.md`, 1952–1992 have a theme on 14–36 % of entries, 1993–2007 on
  66–85 % (target ≥ 90 %). The TF-IDF classifier assigns a code with 87 % held-out precision, but only to 16 % of
  the held-out entries. A theme without a code never got past 64.5 % precision, so nothing was stored. None of the 2,581
  crosswalk rows has a reviewer yet. The top 300 rows cover 62 % of entries, so the review costs days of the editor's time.
- **Search.** Pagefind matches words. A French query does not find a Dutch title on the same subject, and
  "Congo" does not find "Kivu" or "Force publique". Meaning-based, cross-lingual search would help readers more than
  a fixed label set.
- **Similar publications.** Title TF-IDF neighbours fail across languages, and on short titles they mostly match
  shared function words. Embeddings handle both better.

One embedding per record serves all three.

### Prior art: the BNTL search engine

The BNTL site (code: https://github.com/emanjavacas/bntl) already has this feature, and it works well there. What it does:
- **Text per record:** title, then keywords, then abstract, joined with `; ` (`bntl/utils.py`, `convert_to_text`).
- **Model:** `dunzhang/stella_en_1.5B_v5` through sentence-transformers (`prompt_name="s2s_query"`). `BAAI/bge-m3`
  is the commented-out alternative (`vectorizer.py`). The README says encoding needs a reasonably sized GPU.
- **Store and query:** vectors in a Qdrant server, cosine distance. The query is a *record*, not typed text:
  `/vectorQuery?doc_id=…&limit=10` takes that record's vector, returns its 10 nearest neighbours without itself, and
  shows them in the normal result list (`bntl/vector_db.py`, `app.py`).
- **Interface:** one icon button on each record, next to export (`static/templates/reftypes/template.html`). There
  is no "AI" label.

What we keep: neighbours of a record, shown as a normal result list, opened from one icon button. What changes:
- No server. The neighbours are computed offline and stored per record (S4).
- A multilingual model. Stella is English-only, and BHB titles are mostly French and Dutch. `bge-m3` is the BNTL
  alternative and is one of the candidates in §3.
- Our own inline SVG icon: a magic wand, in one colour like the type icons.

## 2. What is built

**S1. Record vectors (offline, in the data release).** Text: title, subtitle, translated title, host title, note.
These are the same fields as the classifier, without the printed heading. Encode with a local multilingual
sentence-embedding model, L2-normalise, and store as int8 in `build/vectors/`. Encoding runs on the laptop during
`bhb release`, not in the Pages workflow. The vectors are shipped in the `data-` release, so CI stays at about 10 minutes.

**S2. Themes and periods by nearest neighbours.** The labelled pool is V-Smart 2009–2017, plus print 1993–2008
entries with an approved code. For an unlabelled entry, take its k = 20 nearest labelled neighbours and weight their
themes by similarity. The theme's score is its share of that weight. The C6 floor stays as it is: a theme is stored
only above the smallest threshold that gives ≥ 90 % precision on the held-out years (V-Smart 2015–2017, print
2005–2008), and never below 0.60. Below that, the entry stays "Not classified". Every such value has `source = semantic`,
`machine = true`, and is shown as "suggested".

The precedence in C7 gets one new rung, after V-Smart codes and before the TF-IDF classifier.

**S3. Crosswalk proposals from the same scores.** Average the neighbour scores over all entries under one old heading
to fill `proposed_code` / `proposal_confidence` in `heading_crosswalk.csv`. Review then changes from "fill 2,581
rows" to "check a sample". A sample check can be done by the editor or by students.

**S4. Similar publications (E8), as on the BNTL.** At most 10 neighbours per record from the same vectors. Exclude the
record itself, its cross-listings, and entries with the same title and the same first author. Keep a neighbour only
above a cosine floor, set from a spot check of 30 random records and logged. Store the ids in `similar` and in the
Pagefind metadata. A magic-wand button in the expanded row and on the record page opens `#/similar/<id>`. That page is the
normal result list, filled with those records by id, with the same export. Its label is "Similar publications /
Publications similaires / Gelijkaardige publicaties", given as tooltip and screen-reader text. The button appears only when
there is at least one neighbour.

**S5. Semantic search on the site (optional, last).** This is the only part that needs the model in the browser, so it is a
separate decision (§4).

## 3. Experiment first (S0, about 1 day, local)

The result decides whether S2–S5 go ahead. Compare, on the existing year split:

| Candidate (open licence, local) | Kind | Why |
|---|---|---|
| `intfloat/multilingual-e5-small` | transformer, 384 d | small, strong multilingual retrieval |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | transformer, 384 d | small, well-known baseline |
| `BAAI/bge-m3` | transformer, 1024 d | strongest of the three; offline only, too large for a browser |
| a Model2Vec static model (e.g. `minishlab/potion-multilingual-128M`) | static token vectors | no transformer at query time; the browser can use it |

Measure, and report in `build/semantic_report.md`:
1. theme precision and coverage of S2 at the thresholds, against TF-IDF (64.5 % best). **Go: ≥ 90 % precision with
   clearly more coverage than today.**
2. a 30-record spot check of neighbours (S4), FR/NL/EN mixed;
3. 20 cross-lingual query pairs (e.g. "béguinages" / "begijnhoven"): recall@10;
4. encoding time for 180,000 records on the laptop, vector size, model size.

Licences and sizes are to be checked when the models are downloaded. The download (Hugging Face) needs your go-ahead.

**Caveat.** The held-out years are modern, so they overstate accuracy before 1993. The 100 pre-1993 rows in the P3
gold sheet are still needed to measure that, now as a sample check rather than a full review.

## 4. Semantic search in the browser: options for later

| Option | Per visit | Quality | Notes |
|---|---|---|---|
| A. Keyword search, then rerank the top hits by vectors stored per record | small (only the vectors of the hits) | finds only what keywords find | no model in the browser; vectors for the hits come from the record shards |
| B. Static model (Model2Vec) + clustered vector shards | tokenizer + a few token-vector shards + nprobe clusters, to be measured | lower than a transformer | fully static; vectors split into about 1,000 clusters so a query fetches a few files, as Pagefind does |
| C. Transformer in the browser (transformers.js, quantised) + clustered shards | model download on first use, likely tens of MB or more | best | opt-in "search by meaning" toggle; heavy on phones |

### Does it fit on GitHub Pages?

Yes, as long as all encoding is done locally. Pages allows 1 GB per site (and about 100 GB of traffic a month). The
workflow fails above 900 MB. The site is **249 MB** today (25 Oct, `site/dist`, 180,224 files, almost all of it
Pagefind). Sizes below are for 179,000 records. The vector sizes are arithmetic; the model sizes are to be confirmed in S0.

| Part | Added to the site | Downloaded per visit |
|---|---|---|
| S2/S3 themes by neighbours | 0 (labels in the records) | 0 |
| S4 similar publications, 10 ids per record | ≈ 30 MB, inside each record's fragment | a few hundred bytes, when a record opens |
| A. vectors for reranking, 384 d int8 | ≈ 69 MB in about 1,000 shard files | a few shards per search |
| B. as A, plus a static token-vector table (Model2Vec, int8, sharded) | ≈ 69 MB + about 100 MB | tokenizer + a few shards |
| C. as A, plus a quantised small transformer (transformers.js) | ≈ 69 MB + about 120 MB | the model on first use (cached afterwards), then a few shards |

Even the largest option (C, with 1024-d vectors from `bge-m3` at ≈ 183 MB) stays at about 600 MB, under the 900 MB
check. Only 384-d query vectors work in the browser, so options B and C would use a small model. `bge-m3` could still be
used offline for S2–S4.

Off the site:
- **Encoding happens on the laptop,** in `bhb release`. The vectors (≈ 70–180 MB) go into the `data-` release as one
  file. A release asset may be up to 2 GB. CI only downloads that file and writes the shards, so the 10-minute Pages
  deployment stays within its limit.
- **Encoding time** on the laptop is estimated at minutes for a small model and up to about an hour for `bge-m3`.
  S0 measures it.
- **The model file is served from the site itself,** not from the Hugging Face CDN, for the same reason the fonts are
  self-hosted: no third-party request.

A fourth option needs no query encoding at all. **D. "More like these results":** run the keyword search as now,
average the stored vectors of the top 20 hits, and use that average as the query against the clustered shards. It
finds titles in other languages on the same subject, at the cost of option A (only shards). It does not help when the
keyword search finds nothing.

The query and the records must be encoded with **the same model**. Vectors from `bge-m3` cannot be searched with a
query from a small model. If B or C is chosen, the site's vectors come from that small model; `bge-m3` vectors can still
drive S2–S4 offline.

Recommendation: decide after S0, between B and C. D can ship first, because it needs no model in the browser. A is a cheap first step if S0 shows the vectors are good but no
model is light enough.

## 5. Order and stop points

| Step | Effort | Stop point |
|---|---|---|
| S0 experiment | about 1 day | **report**: go / no-go for S2 |
| S1–S2 vectors, themes by neighbours, report | 1–2 days | report coverage per year (C8 table) |
| S3 crosswalk proposals | ½ day | sample check by the editor or students |
| S4 similar publications | 1 day | spot check of 30 records |
| S5 browser search | 2–3 days | choose A, B or C |

## 6. Open questions

- Whether the theme facet stays at all, or is dropped for now in favour of meaning-based search. S1/S4/S5 do not
  need the facet; S2/S3 only matter if it stays.
- Whether S2's "suggested" themes may be shown before any pre-1993 sample check.
