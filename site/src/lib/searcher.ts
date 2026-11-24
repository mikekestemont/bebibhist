// A search in two steps: Pagefind ranks the records that hold the words, and the filters, the sort order and the
// filter counts are computed from the same index files (facets.ts). Used by the worker (pagefind-worker.ts), and on
// the page's thread where a browser has no module workers (search.ts). Pagefind must not load a filter file, or it
// counts that filter on every later search: no search it gets names a filter, and ``filters()`` is never called.
import { countPages, filterPages, readFilter, readMeta, sortPages, type FilterCounts, type Filters, type FilterValues, type IndexMeta, type Sort } from "./facets.ts";

export interface SearchOptions {
  filters?: Filters;
  sort?: Sort;
}

/** The ids of the hits, in order, and the number by which their counts can be asked (``counts``). */
export interface Found {
  ids: string[];
  search: number;
}

export interface Ranking {
  pageLength?: number;
  termSimilarity?: number;
}

/** What is used of Pagefind's own module (pagefind.js). */
export interface PagefindModule {
  init: () => Promise<void>;
  options: (settings: { basePath?: string; ranking?: Ranking }) => Promise<void>;
  preload: (query: string) => Promise<void>;
  search: (query: string) => Promise<{ results: { id: string }[] }>;
}

export interface Searcher {
  /** Pagefind's start, with its ranking weights. */
  init: (ranking: Ranking) => Promise<void>;
  /** The index chunks of a word, without a search. */
  preload: (query: string) => Promise<void>;
  /** The hits of a search; with ``null``, every record that passes the filters. */
  search: (query: string | null, options?: SearchOptions) => Promise<Found>;
  /**
   * The filter counts of a search (0: of no hits), or null when it is too long ago. A filter the search uses counts the
   * hits it would have without that filter: the year chart shows every year, and a group with a ticked box what its
   * other boxes would add.
   */
  counts: (search: number) => Promise<FilterCounts | null>;
  /** Reads the filters in advance: the first counts, and the first search that narrows or sorts, wait for them. */
  warm: () => Promise<void>;
}

/** The searches whose counts can be asked: a list's counts are asked as soon as it is shown. */
const KEPT = 32;
/** The rankings kept, the latest used: a search of all text asks for up to three. */
const RANKINGS = 8;

export function createSearcher(pagefind: PagefindModule, basePath: string): Searcher {
  let entry: Promise<string> | null = null;
  let meta: Promise<IndexMeta & { numbers: Map<string, number> }> | null = null;
  const filterValues = new Map<string, Promise<FilterValues>>();
  // A search's ranked ids (null: every record), before its filters.
  const kept = new Map<number, { ranked: string[] | null; filters: Filters }>();
  let last = 0;
  // The ids Pagefind ranked for a query: another page, order or filter of the same search does not rank it again.
  const rankings = new Map<string, Promise<string[]>>();

  function rank(query: string): Promise<string[]> {
    const known = rankings.get(query);
    const ranking = known || pagefind.search(query).then(({ results }) => results.map(({ id }) => id));
    if (!known) ranking.catch(() => rankings.delete(query));
    rankings.delete(query);
    rankings.set(query, ranking);
    if (rankings.size > RANKINGS) rankings.delete(rankings.keys().next().value!);
    return ranking;
  }

  /** The name of the index in use, read as Pagefind starts, so that both read the same one around a deployment. */
  function indexName(): Promise<string> {
    entry ??= fetch(`${basePath}pagefind-entry.json?ts=${Date.now()}`)
      .then((response) => response.json())
      .then((read: { languages: Record<string, { hash: string }> }) => Object.values(read.languages)[0].hash);
    entry.catch(() => { entry = null; });
    return entry;
  }

  function loadMeta() {
    meta ??= (async () => {
      const name = await indexName();
      // An empty search only waits until Pagefind has read its files. This is one of them, so once Pagefind has it, it
      // comes from the browser's cache instead of being downloaded twice (4 MB).
      await pagefind.search("");
      const found = readMeta(await read(`${basePath}pagefind.${name}.pf_meta`));
      return { ...found, numbers: new Map(found.ids.map((id, number) => [id, number])) };
    })();
    // A file that could not be read is asked for again next time.
    meta.catch(() => { meta = null; });
    return meta;
  }

  /** The values of these filters (by default every filter's); a filter the index does not have is left out. */
  async function loadFilters(names?: string[]): Promise<Map<string, FilterValues>> {
    const { filterFiles } = await loadMeta();
    const wanted = (names || [...filterFiles.keys()]).filter((name) => filterFiles.has(name));
    const loaded = await Promise.all(wanted.map((name) => {
      if (!filterValues.has(name)) {
        const loading = read(`${basePath}filter/${filterFiles.get(name)}.pf_filter`).then(readFilter);
        // A file that could not be read is asked for again next time.
        loading.catch(() => filterValues.delete(name));
        filterValues.set(name, loading);
      }
      return filterValues.get(name)!;
    }));
    return new Map(wanted.map((name, index) => [name, loaded[index]]));
  }

  /** The page numbers of ranked ids, or of every record. */
  async function pagesOf(ranked: string[] | null): Promise<Uint32Array> {
    const { ids, numbers } = await loadMeta();
    if (!ranked) return Uint32Array.from(ids, (_, number) => number);
    return Uint32Array.from(ranked, (id) => {
      const number = numbers.get(id);
      if (number === undefined) throw new Error(`search index: no page ${id}`);
      return number;
    });
  }

  async function narrowed(pages: Uint32Array, filters: Filters): Promise<Uint32Array> {
    const names = Object.keys(filters);
    if (!names.length) return pages;
    return filterPages(pages, filters, await loadFilters(names), (await loadMeta()).ids.length);
  }

  return {
    async init(ranking) {
      indexName().catch(() => {});
      // Pagefind finds its index next to its own script only on a page's thread; in a worker it falls back to
      // "/pagefind/", which is not where the site is published (/bebibhist/pagefind/). So it is told.
      await pagefind.options({ basePath, ranking });
      await pagefind.init();
    },
    preload: (query) => pagefind.preload(query),
    async search(query, options = {}) {
      const filters = options.filters || {};
      // Read while Pagefind ranks.
      const narrows = Object.keys(filters).length > 0 || Boolean(options.sort);
      if (narrows) loadFilters(Object.keys(filters)).catch(() => {});
      const ranked = query === null ? null : await rank(query);
      const search = (last += 1);
      kept.set(search, { ranked, filters });
      kept.delete(search - KEPT);
      // The ranked list needs nothing more: a first search does not wait for the filters.
      if (ranked && !narrows) return { ids: ranked, search };
      const pages = await narrowed(await pagesOf(ranked), filters);
      const { ids, ranks } = await loadMeta();
      const ordered = options.sort ? sortPages(pages, options.sort, ranks) : pages;
      return { ids: Array.from(ordered, (page) => ids[page]), search };
    },
    async counts(search) {
      const asked = search === 0 ? { ranked: [], filters: {} } : kept.get(search);
      if (!asked) return null;
      const [values, { ids }, pages] = await Promise.all([loadFilters(), loadMeta(), pagesOf(asked.ranked)]);
      const counts = countPages(await narrowed(pages, asked.filters), values, ids.length);
      for (const [name, own] of values) {
        if (!asked.filters[name]) continue;
        const { [name]: _, ...others } = asked.filters;
        Object.assign(counts, countPages(await narrowed(pages, others), new Map([[name, own]]), ids.length));
      }
      return counts;
    },
    async warm() {
      await loadFilters();
    },
  };
}

const SIGNATURE = "pagefind_dcd".length;

/** The contents of one of Pagefind's gzip files, after its signature. Their names change with their contents. */
async function read(url: string): Promise<Uint8Array> {
  const response = await fetch(url, { cache: "force-cache" });
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return (await gunzip(new Uint8Array(await response.arrayBuffer()))).subarray(SIGNATURE);
}

/** The contents of a gzip file; a server that sent it already unpacked (Content-Encoding: gzip) is read as it is. */
export async function gunzip(bytes: Uint8Array): Promise<Uint8Array> {
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return bytes;
  const stream = new Blob([bytes as BlobPart]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}
