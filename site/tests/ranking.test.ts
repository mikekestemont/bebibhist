import assert from "node:assert/strict";
import { copyFile, cp, mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { close, createIndex } from "pagefind";

import { ensureEntry, splitTable, writeIndexFiles } from "../scripts/index-files.mjs";
import { averageWords, loadable, matchTerms, mayHold, preloads, rankPages, readChunk, taggedWords } from "../src/lib/ranking.ts";
import { RECORDS_PER_FILE, readMeta } from "../src/lib/facets.ts";
import { createSearcher, gunzip, type PagefindModule } from "../src/lib/searcher.ts";

// A small index made by Pagefind itself, with tagged words as the site's (scripts/build-index.mjs), and Pagefind's own
// search over it, with its scores: what is ranked here must equal it.
type Scored = { search: (query: string, options?: { sort: Record<string, string> }) => Promise<{ results: { id: string; score: number }[] }> };
const ranking = { pageLength: 0.4, termSimilarity: 10 };
const BASE = "http://index.test/";
// The index as Pagefind wrote it, with its sort orders and ids.
const WHOLE = "http://whole.test/";
const RECORDS = 400;
const realFetch = globalThis.fetch;
let dir = "";
let pagefind: PagefindModule & Scored;
let whole: PagefindModule & Scored;
/** The ids Pagefind gave the records, by number. */
let ids: string[];

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

async function contents(file: string): Promise<Uint8Array> {
  return (await gunzip(new Uint8Array(await readFile(file)))).subarray("pagefind_dcd".length);
}

async function indexName(from: string): Promise<string> {
  return JSON.parse(await readFile(path.join(from, "pagefind-entry.json"), "utf8")).languages.und.hash;
}

async function table(from: string): Promise<Uint8Array> {
  return contents(path.join(from, `pagefind.${await indexName(from)}.pf_meta`));
}

before(async () => {
  dir = await mkdtemp(path.join(tmpdir(), "bhb-ranking-"));
  const { index } = await createIndex({ forceLanguage: "und" });
  for (let record = 0; record < RECORDS; record += 1) {
    // Few years, so that many records share one, and a name that some records lack.
    const sort = { year: String(1950 + (record * 7) % 31), ...(record % 4 ? { name: `n${(record * 37) % 101}` } : {}) };
    await index!.addCustomRecord({ url: `#/${record}`, language: "und", content: wordsOf(record).map((word) => `aw_${word}_`).join(" "), meta: { id: `bhb:${record}`, title: String(record) }, sort });
  }
  await index!.writeFiles({ outputPath: dir });
  await close();
  await ensureEntry(dir, RECORDS);
  // Named as a module, which Node takes a lone .js file not to be.
  await copyFile(path.join(dir, "pagefind.js"), path.join(dir, "pagefind.mjs"));
  await cp(dir, `${dir}-whole`, { recursive: true });
  ids = splitTable(await table(dir)).ids;
  await writeIndexFiles(dir, new Map(Array.from({ length: RECORDS }, (_, record) => [`bhb:${record}`, { og: wordsOf(record).join(" ") }])));
  globalThis.fetch = (async (url: string) => {
    const { origin, pathname } = new URL(String(url));
    return new Response(await readFile(path.join(`${origin}/` === WHOLE ? `${dir}-whole` : dir, pathname)));
  }) as typeof fetch;
  const start = async (from: string, basePath: string) => {
    const started = await import(pathToFileURL(path.join(from, "pagefind.mjs")).href);
    await started.options({ basePath, ranking });
    await started.init();
    return started;
  };
  pagefind = await start(dir, BASE);
  whole = await start(`${dir}-whole`, WHOLE);
});

after(async () => {
  globalThis.fetch = realFetch;
  await rm(dir, { recursive: true, force: true });
  await rm(`${dir}-whole`, { recursive: true, force: true });
});

const QUERIES = [
  "aw_histoire", "aw_histoire_", "aw_belg", "aw_belgique_ aw_histoire", "aw_bruges aw_histoires_", "aw_mot1", "aw_mot12 aw_histoire_",
  // Terms that begin one another, or come twice.
  "aw_belg aw_belgique", "aw_histoire aw_hist", "aw_hist aw_histoire aw_histoires", "aw_bruges aw_bruges",
];

test("hits and scores equal Pagefind's, to the last bit", async () => {
  const meta = readMeta(await table(dir));
  for (const query of QUERIES) {
    const terms = taggedWords(query)!;
    const chunks = meta.chunks.filter((chunk) => terms.some((term) => mayHold(chunk, term)));
    for (const { from } of chunks) await pagefind.preload(from);
    const expected = new Map((await pagefind.search(query)).results.map(({ id, score }) => [id, score]));
    const words = (await Promise.all(chunks.map((chunk) => contents(path.join(dir, `index/${chunk.file}.pf_index`))))).flatMap((bytes) => readChunk(bytes, (word) => terms.some((term) => word.startsWith(term))));
    const { pages, scores } = rankPages(matchTerms(terms, words, meta.wordCounts.length), meta.wordCounts, averageWords(meta.wordCounts), ranking);
    assert.ok(pages.length > 0, query);
    assert.deepEqual(new Map([...pages].map((page) => [String(page), scores[page]])), expected, query);
    // The best first; equal scores in the order of the index.
    for (let at = 1; at < pages.length; at += 1) {
      assert.ok(scores[pages[at - 1]] > scores[pages[at]] || (scores[pages[at - 1]] === scores[pages[at]] && pages[at - 1] < pages[at]), query);
    }
  }
});

test("a list sorted from the files of the sort orders is sorted as Pagefind sorts", async () => {
  assert.equal((await readdir(path.join(dir, "sort"))).length, 2);
  const searcher = createSearcher(pagefind, BASE);
  await searcher.init(ranking);
  for (const query of ["aw_histoire_", "aw_belg", "aw_mot1"]) {
    await whole.preload(query);
    for (const sort of [{ year: "asc" }, { year: "desc" }, { name: "asc" }, { name: "desc" }] as Record<string, "asc" | "desc">[]) {
      const expected = (await whole.search(query, { sort })).results.map(({ id }) => id);
      assert.ok(expected.length > 100, query);
      assert.deepEqual(Array.from((await searcher.search(query, { sort })).pages, (page) => ids[page]), expected, `${query} ${JSON.stringify(sort)}`);
    }
  }
});

test("Pagefind ranks the same over the records' numbers as over its own ids", async () => {
  for (const query of QUERIES) {
    await pagefind.preload(query);
    await whole.preload(query);
    const own = (await whole.search(query)).results.map(({ id, score }) => [id, score]);
    assert.deepEqual((await pagefind.search(query)).results.map(({ id, score }) => [ids[Number(id)], score]), own, query);
  }
});

test("the record of a number is the one Pagefind has under its id", async () => {
  const name = await indexName(dir);
  assert.equal((await readdir(path.join(dir, "records", name))).length, Math.ceil(RECORDS / RECORDS_PER_FILE));
  for (let page = 0; page < RECORDS; page += 1) {
    const file = path.join(dir, "records", name, `${Math.floor(page / RECORDS_PER_FILE)}.bin`);
    const record = JSON.parse(new TextDecoder().decode(await gunzip(new Uint8Array(await readFile(file)))))[page % RECORDS_PER_FILE];
    const fragment = JSON.parse(new TextDecoder().decode(await contents(path.join(`${dir}-whole`, "fragment", `${ids[page]}.pf_fragment`))));
    assert.deepEqual(record, { m: fragment.meta, w: { og: wordsOf(Number(fragment.meta.title)).join(" ") } });
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
  const quick = createSearcher(counting, BASE, { slow: 0 });
  await quick.init(ranking);
  const found = await quick.search("aw_histoire");
  assert.deepEqual(asked, []);
  assert.deepEqual([...found.pages].sort(), [...known.pages].sort());
  // A word that begins no word of the index has no hits, where Pagefind falls back on a word that begins it.
  assert.equal((await quick.search("aw_zzzz")).pages.length, 0);
  assert.equal((await patient.search("aw_histoire aw_zzzz")).pages.length, 0);
  assert.deepEqual(asked, []);
  // An entry's id stays with Pagefind.
  await quick.search("bhb:1996-1");
  assert.deepEqual(asked, ["bhb:1996-1"]);
});

test("the chunks that can hold a word's longer words are all found", () => {
  // As Pagefind stores them: the ends shortened, so a word may lie between two chunks ("aw_beguinages"), or a chunk
  // end before it begins ("aw_bibliothekenp" to "aw_biblioth", with aw_bibliotheque_ in it).
  const ends = [["aa", "aw_beguinag"], ["aw_beguinal", "aw_belgie"], ["aw_belgiea", "aw_bibliotheken"], ["aw_bibliothekenp", "aw_biblioth"], ["aw_bibliotu", "aw_gent"], ["aw_gh", "zz"]];
  const chunks = ends.map(([from, to], at) => ({ from, to, until: ends[at + 1]?.[0] ?? "~", file: String(at) }));
  const holding = (term: string) => chunks.filter((chunk) => mayHold(chunk, term)).map(({ file }) => file).join("");
  assert.equal(holding("aw_beguinages"), "0");
  assert.equal(holding("aw_belg"), "12");
  assert.equal(holding("aw_belgie_"), "1");
  assert.equal(holding("aw_bibliotheque_"), "3");
  assert.equal(holding("aw_bib"), "234");
  assert.equal(holding("aw_zut"), "5");
  assert.deepEqual(chunks.filter((chunk) => !loadable(chunk)).map(({ file }) => file), ["3"]);
});

test("only an entry's id is searched otherwise than as words of the index", () => {
  assert.deepEqual(taggedWords("aw_histoire sc_0123456789 au_vanderweyden_"), ["aw_histoire", "sc_0123456789", "au_vanderweyden_"]);
  assert.deepEqual(taggedWords("aw_œuvre"), ["aw_œuvre"]);
  for (const query of ["bhb:vs-1252259", "13322", "aw_l'abbaye"]) assert.equal(taggedWords(query), null);
  assert.deepEqual(preloads("bhb 1996"), ["bhbzz", "bh", "1996zz", "199", "19"]);
});
