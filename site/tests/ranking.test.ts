import assert from "node:assert/strict";
import { copyFile, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { close, createIndex } from "pagefind";

import { chunksFor, matchTerms, preloads, rankable, rankPages, averageWords, readChunk } from "../src/lib/ranking.ts";
import { createSearcher, gunzip, type PagefindModule } from "../src/lib/searcher.ts";
import { readMeta } from "../src/lib/facets.ts";

// A small index made by Pagefind itself, with tagged words as the site's (scripts/build-index.mjs), and Pagefind's own
// search over it, with its scores: what is ranked here must equal it.
type Scored = { search: (query: string) => Promise<{ results: { id: string; score: number }[] }> };
const ranking = { pageLength: 0.4, termSimilarity: 10 };
const BASE = "http://index.test/";
const realFetch = globalThis.fetch;
let dir = "";
let pagefind: PagefindModule & Scored;

/** Words of which some are on most records and some on few, in a fixed but uneven pattern. */
function wordsOf(record: number): string[] {
  const words = ["histoire"];
  if (record % 3) words.push("belgique");
  if (record % 7 === 0) words.push("histoires", "histoire", "histoire");
  if (record % 11 === 0) words.push("historien");
  if (record % 5 === 0) words.push("bruges", "belge");
  for (let more = 0; more < (record * 7) % 23; more += 1) words.push(`mot${(record * 13 + more * 17) % 211}`);
  return words;
}

before(async () => {
  dir = await mkdtemp(path.join(tmpdir(), "bhb-ranking-"));
  const { index } = await createIndex({ forceLanguage: "und" });
  for (let record = 0; record < 400; record += 1) {
    await index!.addCustomRecord({ url: `#/${record}`, language: "und", content: wordsOf(record).map((word) => `aw_${word}_`).join(" "), meta: { title: String(record) } });
  }
  await index!.writeFiles({ outputPath: dir });
  await close();
  globalThis.fetch = (async (url: string) => new Response(await readFile(path.join(dir, new URL(String(url)).pathname)))) as typeof fetch;
  // Named as a module, which Node takes a lone .js file not to be.
  await copyFile(path.join(dir, "pagefind.js"), path.join(dir, "pagefind.mjs"));
  pagefind = await import(pathToFileURL(path.join(dir, "pagefind.mjs")).href);
  await pagefind.options({ basePath: BASE, ranking });
  await pagefind.init();
});

after(async () => {
  globalThis.fetch = realFetch;
  await rm(dir, { recursive: true, force: true });
});

const QUERIES = ["aw_histoire", "aw_histoire_", "aw_belg", "aw_belgique_ aw_histoire", "aw_bruges aw_histoires_", "aw_mot1", "aw_mot12 aw_histoire_"];

test("hits and scores equal Pagefind's, to the last bit", async () => {
  const entry = JSON.parse(await readFile(path.join(dir, "pagefind-entry.json"), "utf8"));
  const file = async (name: string) => (await gunzip(new Uint8Array(await readFile(path.join(dir, name))))).subarray("pagefind_dcd".length);
  const meta = readMeta(await file(`pagefind.${entry.languages.und.hash}.pf_meta`));
  for (const query of QUERIES) {
    for (const word of preloads(query)) await pagefind.preload(word);
    const expected = new Map((await pagefind.search(query)).results.map(({ id, score }) => [id, score]));
    const terms = rankable(query)!;
    const chunks = [...new Set([...preloads(query), query].flatMap((words) => chunksFor(words, meta.chunks)))];
    const words = (await Promise.all(chunks.map((chunk) => file(`index/${chunk.file}.pf_index`)))).flatMap((bytes) => readChunk(bytes, (word) => terms.some((term) => word.startsWith(term))));
    const { pages, scores } = rankPages(matchTerms(terms, words, meta.wordCounts.length)!, meta.wordCounts, averageWords(meta.wordCounts), ranking);
    assert.ok(pages.length > 0, query);
    assert.deepEqual(new Map([...pages].map((page) => [meta.ids()[page], scores[page]])), expected, query);
    // The best first; equal scores in the order of the index.
    for (let at = 1; at < pages.length; at += 1) {
      assert.ok(scores[pages[at - 1]] > scores[pages[at]] || (scores[pages[at - 1]] === scores[pages[at]] && pages[at - 1] < pages[at]), query);
    }
  }
});

test("only a search Pagefind would take long over is ranked here", async () => {
  let asked: string[] = [];
  const counting: PagefindModule = { ...pagefind, init: pagefind.init, options: pagefind.options, preload: pagefind.preload, search: (query) => {
    if (query) asked.push(query);
    return pagefind.search(query);
  } };
  const patient = createSearcher(counting, BASE);
  await patient.init(ranking);
  const known = await patient.search("aw_histoire");
  assert.deepEqual(asked, ["aw_histoire"]);
  asked = [];
  const quick = createSearcher(counting, BASE, { slow: 0, slowBytes: 0 });
  await quick.init(ranking);
  const found = await quick.search("aw_histoire");
  assert.deepEqual(asked, []);
  assert.deepEqual([...found.ids].sort(), [...known.ids].sort());
  // Ids, a word that begins no index word, and words that begin one another stay with Pagefind.
  for (const query of ["bhb:1996-1", "aw_zzzz", "aw_histoire aw_histoires"]) await quick.search(query);
  assert.deepEqual(asked, ["bhb:1996-1", "aw_zzzz", "aw_histoire aw_histoires"]);
});

test("the chunks of a query are those Pagefind loads", () => {
  const chunks = [["aa", "aw_beguinag"], ["aw_beguinal", "aw_gent"], ["aw_gh", "zz"]].map(([from, to], at) => ({ from, to, until: "", file: String(at) }));
  const files = (query: string) => chunksFor(query, chunks).map(({ file }) => file);
  assert.deepEqual(files("aw_abbaye"), ["0"]);
  assert.deepEqual(files("aw_gent aw_abbaye"), ["1", "0"]);
  // Between two chunks, whose ends are shortened: by the letters they share.
  assert.deepEqual(files("aw_beguinages"), ["0"]);
  assert.deepEqual(files("aw_gentzz"), ["1"]);
  assert.deepEqual(preloads("aw_gent"), ["aw_gentzz", "aw_gen", "aw_ge"]);
  assert.deepEqual(preloads("bhb 1996"), ["bhbzz", "bh", "1996zz", "199", "19"]);
});
