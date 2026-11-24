# A new delivery: from the file to the site

For a volume that arrives as a Word manuscript or a typeset proof (2022 and 2023 are expected; a corrected file for an
earlier year goes the same way). The commands run in `pipeline/` unless said otherwise. The release chain itself is in
`pipeline/README.md`; this is the order of a delivery and what to look at between the steps.

## 1. Receive

- Put the file in `<raw>/manuscripts/`, named with its year (`BGBBHB2022.docx`), and add it to `SOURCES.md` there with its
  origin, date and SHA-256. One file per year: an older version, or a Word file whose proof has come, goes to `superseded/`.
  A name without a year, two files of a year and the old `.doc` format stop the reading.
- `bhb ingest manuscript --check` reads everything and writes nothing. Look at:
  - the entries: 8,900–9,150 in each of 2018–2021;
  - "without a code": 0 so far; a heading listed there is spelled otherwise than in `data/curated/scheme.csv`;
  - "tracked changes" in a file's report: the text is read as if every change were accepted (inserted
    text counts, deleted text does not, moved text stands at its new place). Ask for an accepted copy when there are many;
  - "gone" for a year that was there before: a corrected text gives its entry a new id. Its rows in
    `data/curated/corrections.csv` and `identifiers_by_hand.csv` then have to move to the new id, and links to the old
    id stop working.
- **A new volume goes on the site only after Mike's go** (24 Nov 2026: 2022 and 2023 too). The chain reads every file in the folder,
  so process and compare, and publish nothing before that. Ask for final files with the tracked changes accepted.

## 2. Run

1. `git status` clean for `data/curated/` (the journal list keeps the ids of the committed one).
2. `bhb chain --to language`: build, journals, identifiers, language.
3. `bhb citations run --dry-run`: the price. The pass keeps every answer whose printed text is unchanged and asks only for
   the others; a Word manuscript is read from its formatting and not parsed, so a delivery costs its titles' translations
   (25 a request). A count of parse requests far above the changed entries means something else changed: stop there.
4. `bhb chain --from citations-run --max-parse N --max-translate N --map --remote-names` with the numbers agreed on. The map is
   made again because a saved layout has no place for new entries; its names are new too, so read them, and add rows to
   `topic_name_fixes.csv`.
   Crossref is asked for the new entries only, one question a second: a volume takes two to three hours, more when it
   throttles (the run pauses and goes on by itself). VABB and KBR come after the citation pass, never before.
5. `bhb compare` runs before the release is packed and stops the chain when something went missing (`build/compare.md`).
   Explain every line under "To look at" before going on with `bhb chain --from release`.

## 3. Publish (after a go)

1. Commit `data/curated/` and everything under `site/`; check the texts that name years (the About page, "Where the data
   comes from").
2. `npm --prefix site run verify`; widen a search check's count range the new data rightly leave; commit; verify again with
   `-- --no-index`; `npm --prefix site run pack`.
3. `gh release create data-YYYY-MM-DD build/release/records.jsonl.gz build/release/NOTES.md build/release/site-dist.tar.gz
   --target <main's commit> …`. A failing search check on the runner that passes here is a slow search, not bad luck: look at it
   rather than running it again.
4. Copy `build/records.jsonl` to `build/records.deployed-YYYY-MM-DD.jsonl`.

## What went wrong on 24 Nov 2026, and where it is guarded now

| What happened | Guard |
|---|---|
| 1,875 parse requests for 313 changed entries (shifted batches) | `citations run` keeps answers made from the same text |
| KBR matched on a fresh build: 440 links lost | `match-kbr` after `citations apply` in the chain |
| Journals lost their ids to a spelling with a full stop, or to a count below the minimum | `_abbreviated`, `keep_previous` in `bhb/journals.py` |
| A build without the two flags would drop 2009–2021 | the chain passes them; `bhb compare` sees a year shrink |
| Losses found only by scripts written for the occasion | `bhb compare`, in the chain |
| Crossref throttled a run of 45,000 questions | `Throttled`, `--patient` |
| The site took over an hour to build on GitHub | built and checked locally, published as it is |
| Two searches at the 20-second limit, passed on a second try | filters, sorting and counts outside Pagefind |
