import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { gzipSync } from "node:zlib";

import { countPages, filterPages, readFilter, readMeta, sortPages } from "../src/lib/facets.ts";
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

// Five records: 0 and 3 are medieval, 1 is both; 4 has no language; "order" lacks record 2.
const IDS = ["und_aaaaaaa", "und_bbbbbbb", "und_ccccccc", "und_ddddddd", "und_eeeeeeee"];
const META = ["1.4.0", IDS.map((id, index) => [id, 100000 + index]), [["aw_abbaye", "aw_béguin", "und_1"]],
  [["period", "und_p"], ["language", "und_l"], ["pubyear", "und_y"]], [["order", [3, 1, 4, 0]]]];
const FILES: Record<string, unknown> = {
  "pagefind.und_x.pf_meta": META,
  "filter/und_p.pf_filter": ["period", [["medieval", [0, 1, 3]], ["contemporary", [1, 2, 4]]]],
  "filter/und_l.pf_filter": ["language", [["nl", [0, 1]], ["fr", [2, 3]]]],
  "filter/und_y.pf_filter": ["pubyear", [["1990", [0, 2]], ["1991", [1]], ["2021", [3, 4]]]],
};
const bytes = (name: string) => Uint8Array.from(cbor(FILES[name]));
const VALUES = new Map([["period", "und_p"], ["language", "und_l"], ["pubyear", "und_y"]].map(([name, file]) => [name, readFilter(bytes(`filter/${file}.pf_filter`))] as const));
const pages = (...list: number[]) => Uint32Array.from(list);

test("the index files are read: ids, filter files, sort orders, values", () => {
  const meta = readMeta(bytes("pagefind.und_x.pf_meta"));
  assert.deepEqual(meta.ids, IDS);
  assert.deepEqual([...meta.filterFiles], [["period", "und_p"], ["language", "und_l"], ["pubyear", "und_y"]]);
  assert.deepEqual([...meta.ranks.get("order")!].map((rank) => (rank > 10 ? null : rank)), [3, 1, null, 0, 2]);
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

test("sort orders run both ways and leave out records without the key", () => {
  const { ranks } = readMeta(bytes("pagefind.und_x.pf_meta"));
  assert.deepEqual([...sortPages(pages(0, 1, 2, 3, 4), { order: "asc" }, ranks)], [3, 1, 4, 0]);
  assert.deepEqual([...sortPages(pages(0, 1, 2, 3, 4), { order: "desc" }, ranks)], [0, 4, 1, 3]);
  assert.deepEqual([...sortPages(pages(2, 0), { other: "asc" }, ranks)], [2, 0]);
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
    const signed = [...new TextEncoder().encode("pagefind_dcd"), ...bytes(name)];
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
  assert.deepEqual(asked, ["pagefind-entry.json"]);
  const counts = await searcher.counts(found.search);
  assert.deepEqual(counts!.period, { medieval: 2, contemporary: 2 });
  assert.deepEqual(counts!.pubyear, { "1990": 1, "1991": 1, "2021": 1 });
  const narrowed = await searcher.search("aw_abbaye", { filters: { period: ["contemporary"] }, sort: { order: "asc" } });
  assert.deepEqual(narrowed.ids, [IDS[1], IDS[4]]);
  assert.ok(calls.every((args) => args.length === 1));
  // Each file of the index is read once.
  assert.equal(new Set(asked).size, asked.length);
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

test("the counts of no hits are zero, and those of a search long ago are gone", async () => {
  const { searcher } = searcherOver([IDS[0]]);
  await searcher.init({});
  assert.deepEqual((await searcher.counts(0))!.period, { medieval: 0, contemporary: 0 });
  const first = await searcher.search("aw_abbaye");
  for (let again = 0; again < 40; again += 1) await searcher.search("aw_abbaye");
  assert.equal(await searcher.counts(first.search), null);
});
