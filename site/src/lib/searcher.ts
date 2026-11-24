// A search in two steps: Pagefind ranks the records that hold the words (ranking.ts, where Pagefind would take long),
// and the filters, the sort order and the filter counts are computed from the same index files (facets.ts). Used by the worker (pagefind-worker.ts), and on
// the page's thread where a browser has no module workers (search.ts). Pagefind must not load a filter file, or it
// counts that filter on every later search: no search it gets names a filter, and ``filters()`` is never called.
import { countPages, filterPages, readFilter, readMeta, readRank, sortPages, type FilterCounts, type Filters, type FilterValues, type IndexMeta, type Sort } from "./facets.ts";
import { averageWords, loadable, matchTerms, mayHold, preloads, rankPages, readChunk, SLOW, taggedWords, type Ranking } from "./ranking.ts";

export interface SearchOptions {
  filters?: Filters;
  sort?: Sort;
}

/** The page numbers of the hits, in order, the index they are numbers of, and the number by which their counts can be
 * asked (``counts``). */
export interface Found {
  pages: Uint32Array;
  index: string;
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
  /** Reads the filters in advance: the first counts, and the first search that narrows, wait for them. */
  warm: () => Promise<void>;
}

/** The searches whose counts can be asked: a list's counts are asked as soon as it is shown. */
const KEPT = 32;
/** The rankings kept, the latest used: a search of all text asks for up to three. */
const RANKINGS = 8;

const NO_PAGES = new Uint32Array(0);

export function createSearcher(pagefind: PagefindModule, basePath: string, { slow = SLOW } = {}): Searcher {
  let weights: Ranking = {};
  let entry: Promise<string> | null = null;
  let table: Promise<Uint8Array> | null = null;
  let meta: Promise<IndexMeta> | null = null;
  const filterValues = new Map<string, Promise<FilterValues>>();
  const ranks = new Map<string, Promise<Uint32Array>>();
  // A search's ranked pages (null: every record), before its filters.
  const kept = new Map<number, { ranked: Uint32Array | null; filters: Filters }>();
  let last = 0;
  // The ranked pages of a query: another page, order or filter of the same search does not rank it again.
  const rankings = new Map<string, Promise<Uint32Array>>();

  function rank(query: string): Promise<Uint32Array> {
    const known = rankings.get(query);
    const terms = taggedWords(query);
    const ranking = known || (terms ? rankWords(query, terms) : rankByPagefind(query, preloads(query)));
    if (!known) ranking.catch(() => rankings.delete(query));
    rankings.delete(query);
    rankings.set(query, ranking);
    if (rankings.size > RANKINGS) rankings.delete(rankings.keys().next().value!);
    return ranking;
  }

  let started: Promise<void> | null = null;

  /** Pagefind reads the index's table (0.9 MB) too: it starts when that is in the browser's cache. */
  function start(): Promise<void> {
    started ??= loadTable().then(() => {}, () => {}).then(() => pagefind.init());
    return started;
  }

  const preloaded = new Set<string>();
  let preloading: Promise<void> = Promise.resolve();

  /** The pages as Pagefind ranks them, once it has the chunks of ``words``. */
  async function rankByPagefind(query: string, words: string[]): Promise<Uint32Array> {
    const fresh = words.filter((word) => !preloaded.has(word));
    for (const word of fresh) preloaded.add(word);
    await start();
    // One preload at a time: two searches run side by side for optional function words.
    preloading = preloading.then(async () => {
      for (const word of fresh) await pagefind.preload(word);
    });
    await preloading;
    return Uint32Array.from((await pagefind.search(query)).results, ({ id }) => Number(id));
  }

  let average = 0;

  /**
   * The ranked pages of a search's words, each with every longer word it begins. Pagefind loads one chunk of a word,
   * where its longer words may fill eight: "belg" found 10,928 of 40,160 entries, "nation" none of those with
   * "national" (24 Nov 2026). Here the chunks that can hold them are all read, together, and Pagefind is given them
   * one by one; it finds them in the browser's cache.
   */
  async function rankWords(query: string, terms: string[]): Promise<Uint32Array> {
    const { chunks, wordCounts } = await loadMeta();
    const used = chunks.filter((chunk) => terms.some((term) => mayHold(chunk, term)));
    const files = await Promise.all(used.map(({ file }) => read(`${basePath}index/${file}.pf_index`)));
    const words = files.flatMap((bytes) => readChunk(bytes, (word) => terms.some((term) => word.startsWith(term))));
    const matches = matchTerms(terms, words, wordCounts.length);
    if (!matches.hits) return NO_PAGES;
    if (matches.cost < slow && used.every(loadable)) {
      const pages = await rankByPagefind(query, used.map(({ from }) => from));
      // Pagefind reads its table itself, and around a deployment it may read another index's, where a number means
      // another record: its pages that hold the words are this index's.
      if (pages.every((page) => matches.held[page] === terms.length)) return pages;
    }
    average ||= averageWords(wordCounts);
    return rankPages(matches, wordCounts, average, weights).pages;
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

  /** The place of each page in the order of a sort key. */
  function loadRank(key: string): Promise<Uint32Array> {
    if (!ranks.has(key)) {
      // After the table, which everything waits for and which it would slow down; the words are ranked meanwhile.
      const loading = loadMeta().then(async ({ wordCounts }) =>
        readRank(await gunzip(await load(`${basePath}sort/${await indexName()}.${key}.bin`)), wordCounts.length));
      // A file that could not be read is asked for again next time.
      loading.catch(() => ranks.delete(key));
      ranks.set(key, loading);
    }
    return ranks.get(key)!;
  }

  async function everyPage(): Promise<Uint32Array> {
    return Uint32Array.from((await loadMeta()).wordCounts, (_, page) => page);
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
      const [key, direction] = Object.entries(options.sort || {})[0] || [];
      // Read while Pagefind ranks.
      const narrows = Object.keys(filters).length > 0 || Boolean(key);
      if (narrows) loadFilters(Object.keys(filters)).catch(() => {});
      if (key) loadRank(key).catch(() => {});
      const ranked = query === null ? null : await rank(query);
      const search = (last += 1);
      kept.set(search, { ranked, filters });
      kept.delete(search - KEPT);
      const index = await indexName();
      // The ranked list needs nothing more: a first search does not wait for the filters.
      if (ranked && !narrows) return { pages: ranked, index, search };
      const pages = await narrowed(ranked || (await everyPage()), filters);
      return { pages: key ? sortPages(pages, direction, await loadRank(key)) : pages, index, search };
    },
    async counts(search) {
      const asked = search === 0 ? { ranked: NO_PAGES, filters: {} } : kept.get(search);
      if (!asked) return null;
      const [values, { wordCounts }, pages] = await Promise.all([loadFilters(), loadMeta(), asked.ranked || everyPage()]);
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
