// Pagefind's filters, sort orders and filter counts, read from the files of its index and computed here instead of in
// Pagefind. Pagefind 1.4 counts every value of every filter on every search by looking each of its entries up in the
// list of hits, one hit after the other, twice (``get_filters`` in pagefind_web/src/filter.rs): with 1.3 million
// filter entries that is 0.9 ms a hit, 10.6 s for a subject of 12,000 entries whose hits it finds in 0.1 s (24 Nov
// 2026). It also looks each hit up in a sort order entry by entry (1 s for the same subject). Pagefind counts only the
// filters it has loaded, so the page lets it load none: it ranks the hits, and everything else is done here.
import { Reader } from "./cbor.ts";
import type { Chunk } from "./ranking.ts";

/** A list of values means "all of them", as in Pagefind; `{ any: [...] }` means "one of them" (a range of years). */
export type Filters = Record<string, string[] | { any: string[] }>;

export type Sort = Record<string, "asc" | "desc">;

/** The number of hits with each value of each filter, zeros included. */
export type FilterCounts = Record<string, Record<string, number>>;

/** Filter value → the numbers of its pages (records), as a filter file lists them. */
export type FilterValues = Map<string, Uint32Array>;

/** What is not needed by every search (ids, numbers) is read when it is first asked. */
export interface IndexMeta {
  /** The number of words of each page (record), by its number: the order in which the records were indexed. */
  wordCounts: Uint32Array;
  chunks: Chunk[];
  /** Filter name → the name of its file. */
  filterFiles: Map<string, string>;
  /** The id of each page. */
  ids: () => string[];
  /** Id → page number. */
  numbers: () => Map<string, number>;
  /** Where the list of sort orders begins, for the script that makes them files of their own (scripts/sort-files.mjs). */
  sortsAt: number;
}

const UNSORTED = 0xffffffff;
/** After every word that can be ranked here (``rankable``). */
const END = "~";

function once<T>(make: () => T): () => T {
  let made: T | undefined;
  return () => (made ??= make());
}

/** pagefind.*.pf_meta: [version, [[id, words]], [[from, to, file]], [[filter, file]], [[sort key, [page]]]], the last of
 * them an empty list, since the orders are files of their own (``readRank``). */
export function readMeta(bytes: Uint8Array): IndexMeta {
  const reader = new Reader(bytes);
  reader.list();
  reader.skipText();
  const idsAt = reader.at;
  const wordCounts = new Uint32Array(reader.list());
  for (let page = 0; page < wordCounts.length; page += 1) {
    reader.list();
    reader.skipText();
    wordCounts[page] = reader.number();
  }
  const chunks = Array.from({ length: reader.list() }, () => {
    reader.list();
    return { from: reader.text(), to: reader.text(), until: END, file: reader.text() };
  });
  chunks.forEach((chunk, at) => { chunk.until = chunks[at + 1]?.from ?? END; });
  const filterFiles = new Map<string, string>();
  for (let left = reader.list(); left > 0; left -= 1) {
    reader.list();
    const name = reader.text();
    filterFiles.set(name, reader.text());
  }
  const sortsAt = reader.at;
  const ids = once(() => {
    const again = new Reader(bytes, idsAt);
    return Array.from({ length: again.list() }, () => {
      again.list();
      const id = again.text();
      again.number();
      return id;
    });
  });
  return {
    wordCounts,
    chunks,
    filterFiles,
    ids,
    numbers: once(() => new Map(ids().map((id, number) => [id, number]))),
    sortsAt,
  };
}

/** filter/*.pf_filter: [filter, [[value, [page]]]]. */
export function readFilter(bytes: Uint8Array): FilterValues {
  const reader = new Reader(bytes);
  reader.list();
  reader.skipText();
  const values: FilterValues = new Map();
  for (let left = reader.list(); left > 0; left -= 1) {
    reader.list();
    const value = reader.text();
    values.set(value, reader.numbers());
  }
  return values;
}

/** sort/*.bin: the pages in the order of a sort key, three bytes each, the highest byte of all of them first. Gives the
 * place of each page in that order (by page number); ``UNSORTED`` for a page without the key. */
export function readRank(bytes: Uint8Array, total: number): Uint32Array {
  const rank = new Uint32Array(total).fill(UNSORTED);
  const count = bytes.length / 3;
  for (let place = 0; place < count; place += 1) {
    rank[(bytes[place] << 16) | (bytes[count + place] << 8) | bytes[2 * count + place]] = place;
  }
  return rank;
}

/** ``pages`` that pass ``filters``, in their order. A filter or a value the index does not have keeps no page. */
export function filterPages(pages: Uint32Array, filters: Filters, values: Map<string, FilterValues>, total: number): Uint32Array {
  // How many of the conditions so far a page meets, one after the other: a page that misses one stays behind.
  const met = new Uint16Array(total);
  let conditions = 0;
  for (const [name, wanted] of Object.entries(filters)) {
    for (const oneOf of Array.isArray(wanted) ? wanted.map((value) => [value]) : [wanted.any]) {
      if (!oneOf.length) continue;
      for (const value of oneOf) {
        for (const page of values.get(name)?.get(value) || []) if (met[page] === conditions) met[page] = conditions + 1;
      }
      conditions += 1;
    }
  }
  return pages.filter((page) => met[page] === conditions);
}

/** ``pages`` in the order of a sort key (``readRank``); pages without the key are left out. */
export function sortPages(pages: Uint32Array, direction: "asc" | "desc", rank: Uint32Array): Uint32Array {
  const sign = direction === "asc" ? 1 : -1;
  return pages.filter((page) => rank[page] !== UNSORTED).sort((a, b) => sign * (rank[a] - rank[b]));
}

/** How many of ``pages`` have each value of the filters in ``values``. */
export function countPages(pages: Uint32Array, values: Map<string, FilterValues>, total: number): FilterCounts {
  const hit = new Uint8Array(total);
  for (const page of pages) hit[page] = 1;
  const counts: FilterCounts = {};
  for (const [name, list] of values) {
    counts[name] = {};
    for (const [value, of] of list) {
      let count = 0;
      for (let at = 0; at < of.length; at += 1) count += hit[of[at]];
      counts[name][value] = count;
    }
  }
  return counts;
}
