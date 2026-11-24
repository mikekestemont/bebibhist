// A search in two steps: Pagefind ranks the records that hold the words (ranking.ts, where Pagefind would take long),
// and the filters, the sort order and the filter counts are computed from the same index files (facets.ts). Used by the worker (pagefind-worker.ts), and on
// the page's thread where a browser has no module workers (search.ts). Pagefind must not load a filter file, or it
// counts that filter on every later search: no search it gets names a filter, and ``filters()`` is never called.
import { countPages, filterPages, readFilter, readMeta, sortPages, type FilterCounts, type Filters, type FilterValues, type IndexMeta, type Sort } from "./facets.ts";
import { averageWords, chunksFor, matchTerms, mayHold, preloads, rankable, rankPages, readChunk, SLOW, SLOW_BYTES, type Chunk, type Ranking } from "./ranking.ts";

export interface SearchOptions {
  filters?: Filters;
  sort?: Sort;
}

/** The ids of the hits, in order, and the number by which their counts can be asked (``counts``). */
export interface Found {
  ids: string[];
  search: number;
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

export function createSearcher(pagefind: PagefindModule, basePath: string, { slow = SLOW, slowBytes = SLOW_BYTES } = {}): Searcher {
  let weights: Ranking = {};
  let entry: Promise<string> | null = null;
  let table: Promise<Uint8Array> | null = null;
  let meta: Promise<IndexMeta> | null = null;
  const filterValues = new Map<string, Promise<FilterValues>>();
  // A search's ranked ids (null: every record), before its filters.
  const kept = new Map<number, { ranked: string[] | null; filters: Filters }>();
  let last = 0;
  // The ranked ids of a query: another page, order or filter of the same search does not rank it again.
  const rankings = new Map<string, Promise<string[]>>();

  function rank(query: string): Promise<string[]> {
    const known = rankings.get(query);
    const ranking = known || rankHere(query).catch(() => null).then((ids) => ids || rankByPagefind(query));
    if (!known) ranking.catch(() => rankings.delete(query));
    rankings.delete(query);
    rankings.set(query, ranking);
    if (rankings.size > RANKINGS) rankings.delete(rankings.keys().next().value!);
    return ranking;
  }

  let started: Promise<void> | null = null;

  /** Pagefind reads the index's table (4 MB) too: it starts when that is in the browser's cache. */
  function start(): Promise<void> {
    started ??= loadTable().then(() => {}, () => {}).then(() => pagefind.init());
    return started;
  }

  const preloaded = new Set<string>();
  let preloading: Promise<void> = Promise.resolve();

  async function rankByPagefind(query: string): Promise<string[]> {
    const words = preloads(query).filter((word) => !preloaded.has(word));
    for (const word of words) preloaded.add(word);
    // Pagefind asks for a search's files one after the other: they are asked together here, so that it finds them in
    // the browser's cache. (Words of another kind it looks up in a form of its own.)
    if (rankable(query)) loadMeta().then(({ chunks }) => Promise.all(chunkUrls(query, chunks).filter((url) => !cached.has(url)).map(loadChunk))).catch(() => {});
    await start();
    // One preload at a time: two searches run side by side for optional function words.
    preloading = preloading.then(async () => {
      for (const word of words) await pagefind.preload(word);
    });
    await preloading;
    return (await pagefind.search(query)).results.map(({ id }) => id);
  }

  /** The files Pagefind loads for a query on a page just opened, or those of them that ``wanted`` chooses. */
  function chunkUrls(query: string, chunks: Chunk[], wanted: (chunk: Chunk) => boolean = () => true): string[] {
    const used = new Set([...preloads(query), query].flatMap((words) => chunksFor(words, chunks)));
    return [...used].filter(wanted).map(({ file }) => `${basePath}index/${file}.pf_index`);
  }

  // The index files the browser's cache has.
  const cached = new Set<string>();

  function loadChunk(url: string): Promise<Uint8Array> {
    cached.add(url);
    return load(url);
  }

  let average = 0;

  /** The ranked ids of a query Pagefind would take long over, from the chunks Pagefind would use; else null. */
  async function rankHere(query: string): Promise<string[] | null> {
    const terms = rankable(query);
    if (!terms) return null;
    const { chunks, wordCounts, ids } = await loadMeta();
    const files = await Promise.all(chunkUrls(query, chunks, (chunk) => terms.some((term) => mayHold(chunk, term))).map(loadChunk));
    if (files.reduce((sum, { length }) => sum + length, 0) < slowBytes) return null;
    const words = (await Promise.all(files.map(unpack))).flatMap((bytes) => readChunk(bytes, (word) => terms.some((term) => word.startsWith(term))));
    const matches = matchTerms(terms, words, wordCounts.length);
    if (!matches || matches.cost < slow) return null;
    average ||= averageWords(wordCounts);
    const all = ids();
    return Array.from(rankPages(matches, wordCounts, average, weights).pages, (page) => all[page]);
  }

  /** The name of the index in use, read just before Pagefind reads it, so that both use the same one around a deployment. */
  function indexName(): Promise<string> {
    entry ??= fetch(`${basePath}pagefind-entry.json?ts=${Date.now()}`)
      .then((response) => response.json())
      .then((read: { languages: Record<string, { hash: string }> }) => Object.values(read.languages)[0].hash);
    entry.catch(() => { entry = null; });
    return entry;
  }

  function loadTable(): Promise<Uint8Array> {
    table ??= indexName().then((name) => load(`${basePath}pagefind.${name}.pf_meta`));
    table.catch(() => { table = null; });
    return table;
  }

  function loadMeta(): Promise<IndexMeta> {
    meta ??= loadTable().then(unpack).then(readMeta);
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
    const { wordCounts, numbers } = await loadMeta();
    if (!ranked) return Uint32Array.from(wordCounts, (_, number) => number);
    const all = numbers();
    return Uint32Array.from(ranked, (id) => {
      const number = all.get(id);
      if (number === undefined) throw new Error(`search index: no page ${id}`);
      return number;
    });
  }

  async function narrowed(pages: Uint32Array, filters: Filters): Promise<Uint32Array> {
    const names = Object.keys(filters);
    if (!names.length) return pages;
    return filterPages(pages, filters, await loadFilters(names), (await loadMeta()).wordCounts.length);
  }

  return {
    async init(ranking) {
      weights = ranking;
      // Pagefind finds its index next to its own script only on a page's thread; in a worker it falls back to
      // "/pagefind/", which is not where the site is published (/bebibhist/pagefind/). So it is told.
      await pagefind.options({ basePath, ranking });
      void start();
    },
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
      const ordered = options.sort ? sortPages(pages, options.sort, ranks()) : pages;
      const all = ids();
      return { ids: Array.from(ordered, (page) => all[page]), search };
    },
    async counts(search) {
      const asked = search === 0 ? { ranked: [], filters: {} } : kept.get(search);
      if (!asked) return null;
      const [values, { wordCounts }, pages] = await Promise.all([loadFilters(), loadMeta(), pagesOf(asked.ranked)]);
      const counts = countPages(await narrowed(pages, asked.filters), values, wordCounts.length);
      for (const [name, own] of values) {
        if (!asked.filters[name]) continue;
        const { [name]: _, ...others } = asked.filters;
        Object.assign(counts, countPages(await narrowed(pages, others), new Map([[name, own]]), wordCounts.length));
      }
      return counts;
    },
    async warm() {
      await loadFilters();
    },
  };
}

const SIGNATURE = "pagefind_dcd".length;

/** One of the index's files as it is stored. Their names change with their contents. */
async function load(url: string): Promise<Uint8Array> {
  const response = await fetch(url, { cache: "force-cache" });
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
}

/** The contents of one of Pagefind's gzip files, after its signature. */
async function unpack(bytes: Uint8Array): Promise<Uint8Array> {
  return (await gunzip(bytes)).subarray(SIGNATURE);
}

async function read(url: string): Promise<Uint8Array> {
  return unpack(await load(url));
}

/** The contents of a gzip file; a server that sent it already unpacked (Content-Encoding: gzip) is read as it is. */
export async function gunzip(bytes: Uint8Array): Promise<Uint8Array> {
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return bytes;
  const stream = new Blob([bytes as BlobPart]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}
