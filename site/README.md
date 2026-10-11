# Local search

A first website over `build/records.jsonl`. French, Dutch and English share one Pagefind index, so a query is not limited to the language of the interface. Place names in `data/curated/place_synonyms.csv` are added to the index in their other forms (Gent also matches Gand and Ghent).

```bash
cd site
npm install
npm run index    # a few minutes; writes site/public/pagefind, which is not committed
npm run dev
```

Open http://127.0.0.1:5173/. The FR / NL / EN control changes the labels and leaves the query in place.

GitHub Pages does not run the Python pipeline. It downloads `records.jsonl.gz` from the latest `data-` release, unpacks it to `build/records.jsonl`, and then runs `npm run index` and `npm run build`.
