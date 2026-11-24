import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, test } from "node:test";
import { gunzipSync, gzipSync } from "node:zlib";

import { splitTable, writeSortFiles } from "../scripts/sort-files.mjs";
import { countPages, filterPages, readFilter, readMeta, readRank, sortPages } from "../src/lib/facets.ts";
import { createSearcher, type PagefindModule } from "../src/lib/searcher.ts";

/** The CBOR of Pagefind's files: lists, texts and whole numbers. */
function cbor(value: unknown): number[] {
  const head = (major: number, size: number): number[] =>
    size < 24 ? [(major << 5) | size]
      : size < 256 ? [(major << 5) | 24, size]
        : size < 65536 ? [(major << 5) | 25, size >> 8, size & 255]
          : [(major << 5) | 26, (size >>> 24) & 255, (size >> 16) & 255, (size >> 8) & 255, size & 255];
  if (typeof value === "number") return head(0, value);
  if (typeof value === "string") {
    const bytes = [...new TextEncoder().encode(value)];
    return [...head(3, bytes.length), ...bytes];
  }
  const list = value as unknown[];
  return [...head(4, list.length), ...list.flatMap(cbor)];
}

// Five records: 0 and 3 are medieval, 1 is both; 4 has no language; "order" lacks record 2. META is the table as Pagefind
// writes it, before its sort orders are taken out.
const IDS = ["und_aaaaaaa", "und_bbbbbbb", "und_ccccccc", "und_ddddddd", "und_eeeeeeee"];
const META = ["1.4.0", IDS.map((id, index) => [id, 100000 + index]), [["aw_abbaye", "aw_béguin", "und_1"], ["aw_bibliothekenp", "aw_biblioth", "und_2"], ["aw_bibliotu", "zz", "und_3"]],
  [["period", "und_p"], ["language", "und_l"], ["pubyear", "und_y"]], [["order", [3, 1, 4, 0]]]];
const { table: TABLE, orders: ORDERS } = splitTable(Uint8Array.from(cbor(META)));
const FILES: Record<string, unknown> = {
  "pagefind.und_x.pf_meta": TABLE,
  "sort/und_x.order.bin": ORDERS.get("order"),
  "index/und_1.pf_index": [[["aw_abbaye_", [[0, [1]], [1, [1]], [4, [1]]]], ["aw_abbayes_", [[2, [1]]]]]],
  "index/und_2.pf_index": [[["aw_bibliotheque_", [[1, [1]], [3, [1]]]]]],
  "index/und_3.pf_index": [[["aw_bibliotheques_", [[0, [1]]]]]],
  "filter/und_p.pf_filter": ["period", [["medieval", [0, 1, 3]], ["contemporary", [1, 2, 4]]]],
  "filter/und_l.pf_filter": ["language", [["nl", [0, 1]], ["fr", [2, 3]]]],
  "filter/und_y.pf_filter": ["pubyear", [["1990", [0, 2]], ["1991", [1]], ["2021", [3, 4]]]],
};
const bytes = (name: string) => (FILES[name] instanceof Uint8Array ? FILES[name] : Uint8Array.from(cbor(FILES[name])));
const VALUES = new Map([["period", "und_p"], ["language", "und_l"], ["pubyear", "und_y"]].map(([name, file]) => [name, readFilter(bytes(`filter/${file}.pf_filter`))] as const));
const pages = (...list: number[]) => Uint32Array.from(list);

test("the index files are read: ids, filter files, values", () => {
  const meta = readMeta(bytes("pagefind.und_x.pf_meta"));
  assert.deepEqual(meta.ids(), IDS);
  assert.equal(meta.numbers().get(IDS[3]), 3);
  assert.deepEqual([...meta.wordCounts], [100000, 100001, 100002, 100003, 100004]);
  assert.deepEqual(meta.chunks, [
    { from: "aw_abbaye", to: "aw_béguin", until: "aw_bibliothekenp", file: "und_1" },
    { from: "aw_bibliothekenp", to: "aw_biblioth", until: "aw_bibliotu", file: "und_2" },
    { from: "aw_bibliotu", to: "zz", until: "~", file: "und_3" },
  ]);
  assert.deepEqual([...meta.filterFiles], [["period", "und_p"], ["language", "und_l"], ["pubyear", "und_y"]]);
  assert.deepEqual([...VALUES.get("period")!.get("medieval")!], [0, 1, 3]);
  const far = readFilter(Uint8Array.from(cbor(["f", [["v", [23, 24, 255, 256, 65535, 65536, 241716]]]])));
  assert.deepEqual([...far.get("v")!], [23, 24, 255, 256, 65535, 65536, 241716]);
  assert.throws(() => readMeta(Uint8Array.from([0x83, 0x61, 0x31, 0x01])), /unexpected byte/);
});

test("filters: a list asks for every value, any for one of them, an unknown one keeps nothing", () => {
  const all = pages(4, 3, 2, 1, 0);
  const keep = (filters: Parameters<typeof filterPages>[1]) => [...filterPages(all, filters, VALUES, 5)];
  assert.deepEqual(keep({ period: ["medieval"] }), [3, 1, 0]);
  assert.deepEqual(keep({ period: ["medieval", "contemporary"] }), [1]);
  assert.deepEqual(keep({ period: ["medieval"], language: ["nl"] }), [1, 0]);
  assert.deepEqual(keep({ pubyear: { any: ["1990", "1991", "1992"] } }), [2, 1, 0]);
  assert.deepEqual(keep({ pubyear: { any: ["1990", "1991"] }, period: ["contemporary"] }), [2, 1]);
  assert.deepEqual(keep({ period: ["ancient"] }), []);
  assert.deepEqual(keep({ year: ["1990"] }), []);
  assert.deepEqual(keep({}), [4, 3, 2, 1, 0]);
});

test("the sort orders are taken out of the table, with their keys", () => {
  assert.deepEqual([...TABLE], cbor([...META.slice(0, 4), []]));
  assert.deepEqual([...readRank(ORDERS.get("order")!, 5)].map((rank) => (rank > 10 ? null : rank)), [3, 1, null, 0, 2]);
  assert.throws(() => splitTable(TABLE), /no sort orders/);
  const far = [241716, 0, 65536, 255, 65535, 256];
  const { orders } = splitTable(Uint8Array.from(cbor(["1.4.0", [], [], [], [["year", [1, 0]], ["title", far]]])));
  assert.deepEqual([...orders.keys()], ["year", "title"]);
  const rank = readRank(orders.get("title")!, 241717);
  assert.deepEqual(far.map((page) => rank[page]), [0, 1, 2, 3, 4, 5]);
  assert.equal(rank.filter((place) => place < far.length).length, far.length);
});

test("the files of the sort orders are named after the table, and a change in either renames both", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "bhb-sort-"));
  const stored = (value: unknown) => gzipSync(Buffer.concat([Buffer.from("pagefind_dcd"), Uint8Array.from(cbor(value))]));
  const named = async (value: unknown, entry: string) => {
    for (const name of await readdir(dir)) await rm(path.join(dir, name), { recursive: true });
    await writeFile(path.join(dir, "pagefind.und_old.pf_meta"), stored(value));
    await writeFile(path.join(dir, "pagefind-entry.json"), entry);
    await writeSortFiles(dir);
    const [table, ...others] = (await readdir(dir)).filter((name) => name.endsWith(".pf_meta"));
    assert.deepEqual(others, []);
    return table.slice("pagefind.".length, -".pf_meta".length);
  };
  const entry = JSON.stringify({ version: "1.4.0", languages: { und: { hash: "und_old", wasm: null, page_count: 5 } } });
  const name = await named(META, entry);
  assert.match(name, /^und_[0-9a-f]{11}$/);
  assert.equal(await readFile(path.join(dir, "pagefind-entry.json"), "utf8"), entry.replace("und_old", name));
  assert.deepEqual(gunzipSync(await readFile(path.join(dir, `pagefind.${name}.pf_meta`))), Buffer.concat([Buffer.from("pagefind_dcd"), TABLE]));
  assert.deepEqual(await readdir(path.join(dir, "sort")), [`${name}.order.bin`]);
  assert.deepEqual(gunzipSync(await readFile(path.join(dir, "sort", `${name}.order.bin`))), ORDERS.get("order"));
  // Pagefind's empty entry is left for the build to write.
  assert.equal(await named(META, ""), name);
  assert.equal(await readFile(path.join(dir, "pagefind-entry.json"), "utf8"), "");
  assert.notEqual(await named([...META.slice(0, 4), [["order", [1, 3, 4, 0]]]], entry), name);
  await assert.rejects(named(META, entry.replace("und_old", "und_other")), /does not name und_old/);
  await rm(dir, { recursive: true });
});

test("sort orders run both ways and leave out records without the key", () => {
  const rank = readRank(ORDERS.get("order")!, 5);
  assert.deepEqual([...sortPages(pages(0, 1, 2, 3, 4), "asc", rank)], [3, 1, 4, 0]);
  assert.deepEqual([...sortPages(pages(0, 1, 2, 3, 4), "desc", rank)], [0, 4, 1, 3]);
});

test("counts hold every value, those of no hit as zero", () => {
  assert.deepEqual(countPages(pages(3, 0), VALUES, 5), {
    period: { medieval: 2, contemporary: 0 },
    language: { nl: 1, fr: 1 },
    pubyear: { "1990": 1, "1991": 0, "2021": 1 },
  });
});

const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

/** A searcher over the files above, and the files it asked for. */
function searcherOver(ranked: string[]) {
  const asked: string[] = [];
  globalThis.fetch = (async (url: string) => {
    const name = String(url).replace("/base/", "").replace(/\?.*/, "");
    asked.push(name);
    if (name === "pagefind-entry.json") return new Response(JSON.stringify({ languages: { und: { hash: "und_x" } } }));
    const signed = [...(name.startsWith("sort/") ? [] : new TextEncoder().encode("pagefind_dcd")), ...bytes(name)];
    // One file as a server sends it that unpacked it already.
    return new Response(name.includes("und_l") ? Uint8Array.from(signed) : gzipSync(Uint8Array.from(signed)));
  }) as typeof fetch;
  const calls: unknown[][] = [];
  const pagefind: PagefindModule = {
    init: async () => {},
    options: async () => {},
    preload: async () => {},
    search: async (...args) => {
      calls.push(args);
      return { results: args[0] ? ranked.map((id) => ({ id })) : [] };
    },
  };
  return { searcher: createSearcher(pagefind, "/base/"), asked, calls };
}

test("a ranked list waits for no filter, and Pagefind is never asked to filter or sort", async () => {
  const { searcher, asked, calls } = searcherOver([IDS[4], IDS[1], IDS[0]]);
  await searcher.init({});
  const found = await searcher.search("aw_abbaye");
  assert.deepEqual(found.ids, [IDS[4], IDS[1], IDS[0]]);
  assert.deepEqual(asked, ["pagefind-entry.json", "pagefind.und_x.pf_meta", "index/und_1.pf_index"]);
  const counts = await searcher.counts(found.search);
  assert.deepEqual(counts!.period, { medieval: 2, contemporary: 2 });
  assert.deepEqual(counts!.pubyear, { "1990": 1, "1991": 1, "2021": 1 });
  const narrowed = await searcher.search("aw_abbaye", { filters: { period: ["contemporary"] }, sort: { order: "asc" } });
  assert.deepEqual(narrowed.ids, [IDS[1], IDS[4]]);
  assert.ok(calls.every((args) => args.length === 1));
  // Each file of the index is read once.
  assert.equal(new Set(asked).size, asked.length);
});

test("only a sorted list reads its sort order, once", async () => {
  const { searcher, asked } = searcherOver([IDS[4], IDS[2], IDS[1], IDS[0]]);
  await searcher.init({});
  const orders = () => asked.filter((name) => name.startsWith("sort/"));
  await searcher.search("aw_abbaye", { filters: { period: ["contemporary"] } });
  await searcher.search(null);
  await searcher.warm();
  assert.deepEqual(orders(), []);
  assert.deepEqual((await searcher.search("aw_abbaye", { sort: { order: "asc" } })).ids, [IDS[1], IDS[4], IDS[0]]);
  assert.deepEqual((await searcher.search(null, { sort: { order: "desc" } })).ids, [IDS[0], IDS[4], IDS[1], IDS[3]]);
  assert.deepEqual(orders(), ["sort/und_x.order.bin"]);
});

test("a sort order that could not be read is asked again next time, and the list waits for it", async () => {
  const { searcher, asked } = searcherOver([IDS[0], IDS[1]]);
  const answering = globalThis.fetch;
  globalThis.fetch = (async (url: string) => (String(url).includes("/sort/") ? new Response("", { status: 503 }) : answering(url))) as typeof fetch;
  await searcher.init({});
  await assert.rejects(searcher.search("aw_abbaye", { sort: { order: "asc" } }), /503/);
  globalThis.fetch = answering;
  assert.deepEqual((await searcher.search("aw_abbaye", { sort: { order: "asc" } })).ids, [IDS[1], IDS[0]]);
  assert.equal(asked.filter((name) => name.startsWith("sort/")).length, 1);
});

test("every longer word is found, through a file Pagefind cannot load too", async () => {
  const { searcher, asked, calls } = searcherOver([IDS[2]]);
  await searcher.init({});
  const query = () => calls.map(([words]) => words).filter(Boolean);
  // Read here, since Pagefind has no way to the second file; the best first, equal scores in the order of the index.
  assert.deepEqual((await searcher.search("aw_bibliotheque")).ids, [IDS[1], IDS[3]]);
  assert.ok(asked.includes("index/und_2.pf_index") && !asked.includes("index/und_1.pf_index"));
  assert.deepEqual((await searcher.search("aw_bibliotheque_")).ids, [IDS[1], IDS[3]]);
  assert.deepEqual([...(await searcher.search("aw_biblio")).ids].sort(), [IDS[0], IDS[1], IDS[3]]);
  assert.deepEqual(query(), []);
  // The others are Pagefind's, which is given the files first.
  assert.deepEqual((await searcher.search("aw_abbaye")).ids, [IDS[2]]);
  assert.deepEqual(query(), ["aw_abbaye"]);
});

test("without words, every record that passes the filters, in the order of the index", async () => {
  const { searcher, calls } = searcherOver([]);
  await searcher.init({});
  assert.deepEqual((await searcher.search(null, { filters: { period: ["contemporary"] } })).ids, [IDS[1], IDS[2], IDS[4]]);
  assert.deepEqual((await searcher.search(null)).ids, IDS);
  assert.ok(calls.every(([query]) => query === ""));
});

test("a filter in use counts the hits without it, the others those with it", async () => {
  const { searcher } = searcherOver(IDS);
  await searcher.init({});
  const found = await searcher.search("aw_abbaye", { filters: { pubyear: { any: ["1990", "1991"] }, language: ["nl"] } });
  assert.deepEqual(found.ids, [IDS[0], IDS[1]]);
  assert.deepEqual(await searcher.counts(found.search), {
    period: { medieval: 2, contemporary: 1 },
    language: { nl: 2, fr: 1 },
    pubyear: { "1990": 1, "1991": 1, "2021": 0 },
  });
  const years = await searcher.search("aw_abbaye", { filters: { pubyear: { any: ["1990"] } } });
  assert.deepEqual((await searcher.counts(years.search))!.pubyear, { "1990": 2, "1991": 1, "2021": 2 });
  const either = await searcher.search(null, { filters: { period: { any: ["medieval", "contemporary"] } } });
  assert.deepEqual((await searcher.counts(either.search))!.period, { medieval: 3, contemporary: 3 });
});

test("another page, order or filter of a search does not rank it again", async () => {
  const { searcher, calls } = searcherOver(IDS);
  await searcher.init({});
  const ranked = () => calls.filter(([query]) => query).map(([query]) => query);
  for (const options of [{}, {}, { filters: { language: ["nl"] } }, { sort: { order: "asc" as const } }]) await searcher.search("aw_abbaye", options);
  assert.deepEqual(ranked(), ["aw_abbaye"]);
  for (let other = 0; other < 8; other += 1) await searcher.search(`aw_${other}`);
  await searcher.search("aw_abbaye");
  assert.equal(ranked().filter((query) => query === "aw_abbaye").length, 2);
});

test("the counts of no hits are zero, and those of a search long ago are gone", async () => {
  const { searcher } = searcherOver([IDS[0]]);
  await searcher.init({});
  assert.deepEqual((await searcher.counts(0))!.period, { medieval: 0, contemporary: 0 });
  const first = await searcher.search("aw_abbaye");
  for (let again = 0; again < 40; again += 1) await searcher.search("aw_abbaye");
  assert.equal(await searcher.counts(first.search), null);
});
