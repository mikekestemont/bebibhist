# Search benchmark (P1)

Measured on 11 Oct 2026. Database: 270,000 synthetic records built by `bhb bench build` from real titles (327 MB, page size 4096, seven 50 MB chunks). Queries run in Chrome through the vendored `sql.js-httpvfs`, against `bhb bench serve`, which answers HTTP range requests.

Fast 4G is the Chrome preset applied in the server: 150 ms delay per range response and 1.6 Mbit/s. SQLite has to read one page before it knows the next, so the requests stay serial. GitHub Pages was not used; a faster pipe would not remove that serial wait.

Opening one row costs a single 64 KB fetch. After that:

| Query | Cold, local | Cold, Fast 4G | Warm | Cold bytes | Requests |
|---|---:|---:|---:|---:|---:|
| (a) rare term | 59 ms | **18.9 s** | 2 ms | 2.6 MB | 40 |
| (b) `histoire` | 56 ms | — | 7 ms | 2.8 MB | 43 |
| (e) 20 result rows | 62 ms | — | 1 ms | 2.9 MB | 45 |
| (c) `histoire` + facet counts, capped at 5,000 hits | 577 ms | — | 50 ms | **55 MB** | 398 |
| (d) year range 1980–1989, count | 90 ms | — | 3 ms | 4.5 MB | 68 |
| (f) export 2,000 rows | 18 ms | — | 6 ms | 2.0 MB | 5 |

(b), (c), (d), (e) and (f) were not repeated on the slow server. Their request counts already say the same thing: about half a second per request, so (c) would take a few minutes and moves 55 MB.

The budget was (a), (b) and (e) under 1.5 s warm and 3 s cold, (c) under 3 s, and no query over 5 MB. Warm passes. Cold (a) is 19 s. (c) is fifty times the byte cap. A smaller SQLite page would not remove the forty serial round trips (40 × 150 ms is already 6 s before any bytes move), and the facet query was already limited to 5,000 hits.

**Decision:** the prototype does not run live `sql.js-httpvfs` queries. Search falls back to Pagefind, with JSON shards for the records, as the spec provides.
