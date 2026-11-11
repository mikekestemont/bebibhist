import { nameWords, personName, personWord } from "./words.js";
export { nameWords };
/** The words the index holds for a record, per tag, space-separated (``storedWords`` in scripts/build-index.mjs):
 * its own text ("og"), the translations' new words ("tw"), its title ("ot"), the translated title's new words
 * ("tt"), its people ("au"), its volume or journal ("in") and its series ("se"). */
export type IndexWords = { og?: string; tw?: string; ot?: string; tt?: string; au?: string; in?: string; se?: string };

export interface Hit {
  url: string;
  words?: IndexWords;
  meta: {
    id: string;
    formerIds?: string;
    /** The other volumes that list the same publication: "year\tnumber\tprinted text|…" (bhb/duplicates.py). */
    alsoListed?: string;
    /** The ids of those listings, which open this entry (ids of now, before any entry's former id). */
    listedIds?: string;
    title: string;
    citation: string;
    year: string;
    number: string;
    section: string;
    source?: string;
    parsedLlm?: string;
    categoryFr?: string;
    categoryNl?: string;
    categoryEn?: string;
    categoryTheme?: string;
    categoryDraft?: string;
    categoryMachine?: string;
    categorySource?: string;
    authors?: string;
    editors?: string;
    preface?: string;
    translators?: string;
    illustrators?: string;
    subtitle?: string;
    host?: string;
    hostSubtitle?: string;
    hostEditors?: string;
    volume?: string;
    issue?: string;
    pages?: string;
    pubyear?: string;
    yearFromVolume?: string;
    yearMachine?: string;
    place?: string;
    publisher?: string;
    imprintMachine?: string;
    /** "1" when the journal name was found by matching, because the catalogue did not export the journal's record. */
    hostMatched?: string;
    /** "1" when the journal or volume is printed as "Ibid." and was taken from the entry printed before. */
    hostFromIbid?: string;
    /** The journal, grouped by `bhb journals apply` across spellings, and its full title. */
    journalId?: string;
    journalTitle?: string;
    orcids?: string;
    /** Given names written out from KBR: "Name (Given)\tgiven name\tdates\tKBR id\tsource|…". */
    fullNames?: string;
    kbr?: string;
    /** "1" when the places were found in the title, not in the printed index. */
    placesSuggested?: string;
    doi?: string;
    /** Set when the DOI leads to a free copy: "openalex" or "persee", the source of that status. */
    free?: string;
    isbn?: string;
    issn?: string;
    /** Per identifier its source, as "doi:crossref|issn:vabb". */
    identifiersFrom?: string;
    inVolume?: string;
    extent?: string;
    seriesTitle?: string;
    seriesNumber?: string;
    kind?: string;
    places?: string;
    placeIds?: string;
    themes?: string;
    specificFr?: string;
    specificNl?: string;
    specificEn?: string;
    specificFrom?: string;
    specificMachine?: string;
    alsoSubjects?: string;
    themesSuggested?: string;
    periods?: string;
    periodsSuggested?: string;
    languages?: string;
    languageFrom?: string;
    similar?: string;
    container?: string;
    containerCount?: string;
  };
}

/** The neighbours stored with a record, best first. */
export function similarOf(meta: Hit["meta"]): { id: string; score: number }[] {
  return (meta.similar || "")
    .split("|")
    .filter(Boolean)
    .map((pair) => {
      const [id, score] = pair.split(" ");
      return { id, score: Number(score) || 0 };
    });
}

/** A printed “Cfr. / Voir / Zie n°” points at another entry in the same volume. */
const CROSS_REF =
  /\s*\[?\s*(?:cfr|voir|zie)\.?\s+n(?:°|º|o|r)\.?\s*(?:\d{2,6}(?:\s*(?:bis|ter|quater))?(?:\s*[,;]\s*|\s+(?:et|en|and)\s+)?)+\]?/gi;

/** An abbreviation that closes a part keeps one stop ("s.n..", "p.."), and the catalogue writes "In :". An ellipsis and a joined form such as "Salsa !..Doc." stay. Cross-references to the printed volume are left out. */
export function presentCitation(text: string): string {
  return text
    .replaceAll("In :", "In:")
    .replace(CROSS_REF, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([.,])/g, "$1")
    .replace(/\.{2,}(?=\s*$)/g, ".")
    .replace(/(?<!\.)\.\.(?=[\s),;:]|$)/g, ".")
    .trim();
}

/** Names between “In:” and the host title edit the mother publication, as in “In: Willaert (Frank). Veelderhande liedekens”. */
export function editorsBeforeHost(citation: string, host?: string): string {
  const title = host?.trim();
  if (!title) return "";
  const text = presentCitation(citation);
  const at = text.search(/In:/);
  if (at < 0) return "";
  const after = text.slice(at + 3).replace(/^\s+/, "");
  const hostAt = after.indexOf(title);
  if (hostAt <= 0) return "";
  const lead = after
    .slice(0, hostAt)
    .trim()
    .replace(/[.\s]+$/, "")
    .replace(/\s*\((?:éds?|eds?|réd|red|dir)\.?\)\s*$/i, "")
    .replace(/\s+(?:éds?|eds?|réd|red|dir)\.?\s*$/i, "")
    .trim();
  const names = splitNames(lead);
  if (names.length === 0 || names.some((name) => !/^\p{Lu}[^(]{0,80}\([^)]+\)$/u.test(name))) return "";
  return joinNames(names);
}

function splitNames(value: string): string[] {
  return value
    .split(/\s*(?:,|&)\s*|\s+et\s+|\s+en\s+/)
    .map((name) => name.trim())
    .filter(Boolean);
}

function joinNames(names: string[]): string {
  if (names.length < 2) return names[0] || "";
  return `${names.slice(0, -1).join(", ")} & ${names.at(-1)}`;
}

/** A contribution's year, taken from the collected volume, when the printed line stops at the pages. */
export function withHostYear(citation: string, year: string | undefined, machine: string | undefined): string {
  if (machine !== "1" || !year || yearIn(citation, year)) return citation;
  const pages = citation.match(/([,.…])(\s*)(pp?\.\s*\d)/i);
  if (pages && pages.index !== undefined) {
    const at = pages.index;
    return `${citation.slice(0, at)}${pages[1]} ${year}, ${pages[3]}${citation.slice(at + pages[0].length)}`;
  }
  if (citation.endsWith(".")) return `${citation.slice(0, -1)}, ${year}.`;
  return `${citation}, ${year}`;
}

function yearIn(text: string, year: string): boolean {
  return new RegExp(`(?<!\\d)${year}(?!\\d)`).test(text);
}

/** The pipeline's placeholder for a host record the State Archives' export lacks (`bhb/merge.py`). */
export const HOST_MISSING = "[host record not exported]";

/** Journal and monograph titles (and their subtitles) are italic; an article or chapter title and subtitle stay roman. */
export function citationHtml(
  citation: string,
  meta: { title?: string; subtitle?: string; host?: string; hostSubtitle?: string; kind?: string; pubyear?: string; yearMachine?: string; inVolume?: string; hostMatched?: string },
  yearNote = "",
  volumeNote = "",
  hostNote = "",
  hostMissing = "",
  hostMissingNote = "",
  shortYearNote = "",
  missingYearNote = "",
): string {
  // A journal or book still missing from the export has no name to show: the line leaves it out ("In: [host record
  // not exported]," goes), and the record's own row says why (reviewer, 9 Nov 2026: it read as the journal's title).
  const missing = (hostMissing || hostMissingNote) && meta.host === HOST_MISSING && meta.hostMatched !== "1";
  const printed = presentCitation(citation || "");
  const shown = withHostYear(missing ? withoutMissingHost(printed) : printed, meta.pubyear, meta.yearMachine);
  let html = escapeHtml(shown);
  if (meta.inVolume) html = withVolume(html, meta.inVolume, meta.host, volumeNote);
  if (meta.yearMachine === "1" && meta.pubyear && yearIn(shown, meta.pubyear)) {
    const note = escapeHtml(yearNote);
    html = html.replace(meta.pubyear, `<span class="derived" title="${note}">${meta.pubyear}</span>`);
  }
  html = withFullYear(html, meta.pubyear, shortYearNote);
  html = withMissingYear(html, meta.pubyear, missingYearNote);
  // The book's title and subtitle are italic wherever they stand after "In:", also after its editors
  // ("In: Deploige (Jeroen), Deneckere (Gita). Mystifying the Monarch").
  // A journal title stands after the article's title, without "In:"; so does a book's after some chapters' titles.
  const titleAt = meta.title ? html.indexOf(escapeHtml(meta.title.trim())) : -1;
  // A chapter printed without "In:" names its book after its own title too ("Ortino (Sergio). La legislazione
  // bancaria … Banca e Industria fra le due guerre …": Guy Vanthemsche, 10 Nov 2026).
  const after = html.search(/In:/) >= 0 ? html.search(/In:/) : (meta.kind === "article" || meta.kind === "chapter") && titleAt >= 0 ? titleAt + escapeHtml(meta.title!.trim()).length : -1;
  if (after >= 0 && !meta.inVolume) {
    for (const part of [missing ? "" : meta.host, meta.hostSubtitle]) {
      const safe = escapeHtml(part?.trim() || "");
      const at = safe ? html.indexOf(safe, after) : -1;
      if (at >= 0) html = `${html.slice(0, at)}<em>${safe}</em>${html.slice(at + safe.length)}`;
    }
  }
  // A catalogue entry whose journal record was not exported: the journal name recovered from a match stands in for
  // the placeholder. (The catalogue's citation is composed by the pipeline, not printed.) It is marked as supplied
  // in the journal row only; in the citation the note is a tooltip, without the dotted underline.
  if (meta.hostMatched === "1" && meta.host) {
    const supplied = `<em title="${escapeHtml(hostNote)}">${escapeHtml(meta.host.trim())}</em>`;
    html = html.replace(HOST_MISSING, supplied);
  }
  // A book's or journal issue's title and subtitle are italic; an article's or chapter's stay roman.
  if (meta.kind === "book" || meta.kind === "journal-issue") {
    for (const part of [meta.title, meta.subtitle]) {
      const text = part?.trim();
      if (text) html = emphasize(html, text);
    }
  }
  return html;
}

/** The line without the export's placeholder for a missing host, and the "In:" before it. */
export function withoutMissingHost(html: string): string {
  return html
    .replace(/\s*\bIn:\s*\[host record not exported\]\s*[,.]?\s*/, " ")
    .replace(/\s*\[host record not exported\]\s*[,.]?\s*/, " ")
    .replace(/ {2,}/g, " ")
    .trim();
}

/**
 * The volumes of the 1950s print the year in two digits ("Nieuw Vlaams Tijdschrift, VI, 51, p. 185–195"): the full
 * year follows in brackets, marked as supplied, where those two digits stand alone once in the line.
 */
function withFullYear(html: string, year: string | undefined, note: string): string {
  if (!year || !/^19[0-5]\d$/.test(year) || yearIn(html, year)) return html;
  const short = new RegExp(`(?<=,\\s)${year.slice(2)}(?=\\s*[,.;]|$)`, "g");
  const found = [...html.matchAll(short)];
  if (found.length !== 1 || found[0].index === undefined) return html;
  const at = found[0].index + 2;
  return `${html.slice(0, at)} <span class="derived" title="${escapeHtml(note)}">[${year}]</span>${html.slice(at)}`;
}

/**
 * A printed entry without any year (the volume's year was implied, about 10,000 entries of the early volumes): the
 * year of the data at the end, in brackets and marked as supplied, so the result list shows it as the record does
 * (Sébastien, 9 Nov 2026). Nothing is added when the text has a year of its own, even another one.
 */
function withMissingYear(html: string, year: string | undefined, note: string): string {
  if (!year || !/^\d{4}$/.test(year) || year === "0000") return html;
  const text = html.replace(/<[^>]*>/g, "");
  if (/(?<!\d)(?:1[5-9]|20)\d\d(?!\d)/.test(text)) return html;
  // A two-digit year that withFullYear could not place (it stands twice) is left as printed as well.
  if (new RegExp(`,\\s${year.slice(2)}(?=\\s*[,.;]|$)`).test(text)) return html;
  const span = ` <span class="derived" title="${escapeHtml(note)}">[${year}]</span>`;
  return html.endsWith(".") ? `${html.slice(0, -1)}${span}.` : `${html}${span}`;
}

/** The volume goes before the pages, as in a printed chapter line, and is marked as supplied. */
function withVolume(html: string, line: string, host: string | undefined, note: string): string {
  let volume = escapeHtml(line);
  const title = host?.trim();
  if (title) volume = volume.replace(escapeHtml(title), `<em>${escapeHtml(title)}</em>`);
  const span = `<span class="derived" title="${escapeHtml(note)}">${volume}</span>`;
  const pages = html.match(/[,.]?\s*(\bpp?\.\s*\d[^]*)$/);
  if (pages && pages.index !== undefined) return `${html.slice(0, pages.index)}. ${span}, ${pages[1]}`;
  return `${html.replace(/\.?$/, "")}. ${span}.`;
}

function emphasize(html: string, text: string): string {
  const safe = escapeHtml(text);
  return html.replace(new RegExp(escapeRegExp(safe)), `<em>${safe}</em>`);
}

export function escapeHtml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export interface SearchResponse {
  results: { id: string; data: () => Promise<Hit> }[];
  filters?: Record<string, Record<string, number>>;
}

/** A list of values means "all of them" in Pagefind; `{ any: [...] }` means "one of them", as for a range of years. */
export type Filters = Record<string, string[] | { any: string[] }>;

/** The publication years from ``from`` to ``to`` (either may be missing), as a filter that matches any of them. */
export function yearFilter(from: number, to: number, now = new Date().getFullYear()): { any: string[] } | null {
  if (!from && !to) return null;
  const start = Math.min(from || 1945, to || now);
  const end = Math.max(from || 1945, to || now);
  const years: string[] = [];
  for (let year = start; year <= end; year += 1) years.push(String(year));
  return { any: years };
}

interface Pagefind {
  init: () => Promise<void>;
  filters: () => Promise<Record<string, Record<string, number>>>;
  search: (
    query: string | null,
    options?: { filters?: Filters; sort?: Record<string, "asc" | "desc"> },
  ) => Promise<SearchResponse>;
  options: (settings: { basePath?: string; ranking?: { pageLength?: number; termSimilarity?: number } }) => Promise<void>;
  preload: (query: string) => Promise<void>;
}

/** Pagefind favours short records (default 0.75), so a short stub could outrank the work it points to.
 * 0.4 kept the top hits of test queries or improved them; 0.1 let long entries such as volumes with
 * their contents take over. */
const PAGE_LENGTH_WEIGHT = 0.4;

/** How much Pagefind favours an index word as long as the query's word over a longer word it begins (default 1).
 * At 10 every entry with the whole word ranks above every entry found only through a longer one: all 5,096 whole
 * "brugge" hits before the 254 through bruggen, brugges …, likewise for gent, kerk and abbaye; at 1 partial hits
 * mixed in from the first place (a Wespelaar bridges article second for Brugge). One search instead of two
 * (Mike, 10 Nov 2026). */
const TERM_SIMILARITY = 10;

let engine: Pagefind | null = null;

export async function loadEngine(): Promise<Pagefind> {
  if (engine) return engine;
  // Resolve against the page, not the bundle. A relative import from /assets/
  // would request /assets/pagefind/, where the index is not deployed.
  const url = new URL(`${import.meta.env.BASE_URL}pagefind/pagefind.js`, document.baseURI).href;
  let loaded: Pagefind;
  try {
    loaded = await workerPagefind(url);
  } catch {
    // A browser without module workers computes on the page's thread, as before.
    const importer = new Function("url", "return import(url)") as (url: string) => Promise<Pagefind>;
    loaded = await importer(url);
  }
  // Pagefind finds its index next to its own script only on a page's thread; in a worker it falls back to
  // "/pagefind/", which is not where the site is published (/bebibhist/pagefind/). So it is told.
  const basePath = url.replace(/pagefind\.js$/, "");
  await loaded.options({ basePath, ranking: { pageLength: PAGE_LENGTH_WEIGHT, termSimilarity: TERM_SIMILARITY } });
  await loaded.init();
  await loaded.filters();
  recordsBase = `${basePath}records/`;
  // A result's data comes from the record files (``recordOf``), not from Pagefind's fragments, which are not published.
  engine = { ...loaded, search: async (query, options) => {
    if (query) await loadPrefixChunks(loaded, query);
    const response = await loaded.search(query, options);
    return { ...response, results: response.results.map(({ id }) => ({ id, data: () => recordOf(id) })) };
  } };
  return engine;
}

let recordsBase = "";
const recordFiles = new Map<string, Promise<Record<string, { m: Hit["meta"]; w?: IndexWords }>>>();

/**
 * The record of a search result, by its Pagefind id ("und_0083ebf"): from the record file named by the id's first
 * three hex digits (records/008.bin, about 28 kB for some 45 records, ``writeRecordFiles`` in
 * scripts/build-index.mjs). Pagefind's one fragment per record made a deployment of 200,000 files, whose copy on
 * GitHub Pages stalled (10 Nov 2026).
 */
export async function recordOf(id: string): Promise<Hit> {
  const key = id.slice(id.indexOf("_") + 1, id.indexOf("_") + 4);
  if (!recordFiles.has(key)) {
    const loading = fetch(`${recordsBase}${key}.bin`).then(async (response) => {
      if (!response.ok) throw new Error(`records/${key}.bin: ${response.status}`);
      return JSON.parse(await gunzipText(new Uint8Array(await response.arrayBuffer())));
    });
    // A file that could not be read is asked for again next time.
    loading.catch(() => recordFiles.delete(key));
    recordFiles.set(key, loading);
  }
  const record = (await recordFiles.get(key)!)[id];
  if (!record) throw new Error(`record ${id} is not in records/${key}.bin`);
  return { url: `#/record/${encodeURIComponent(record.m.id)}`, meta: record.m, words: record.w };
}

/** The text of a gzip file; a server that sent it already unpacked (Content-Encoding: gzip) is read as it is. */
async function gunzipText(bytes: Uint8Array): Promise<string> {
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return new TextDecoder().decode(bytes);
  const stream = new Blob([bytes as BlobPart]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).text();
}

/**
 * Pagefind in a worker (pagefind-worker.ts), behind the same functions: the page's thread stays free while a
 * search computes, so the page answers and the hourglass keeps turning. A result's data is read from the record
 * files (``recordOf``).
 */
async function workerPagefind(url: string): Promise<Pagefind> {
  const worker = new Worker(new URL("./pagefind-worker.ts", import.meta.url), { type: "module" });
  const waiting = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void }>();
  let next = 0;
  const failed = new Promise<never>((_, reject) => {
    worker.onerror = (event) => {
      event.preventDefault();
      reject(new Error(event.message || "worker failed"));
    };
  });
  worker.onmessage = (event: MessageEvent<{ id: number; value?: unknown; error?: string }>) => {
    const { id, value, error } = event.data;
    const call = waiting.get(id);
    waiting.delete(id);
    if (error) call?.reject(new Error(error));
    else call?.resolve(value);
  };
  const call = <T>(method: string, ...args: unknown[]): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      const id = (next += 1);
      waiting.set(id, { resolve, reject });
      worker.postMessage({ id, method, args });
    });
  await Promise.race([call("load", url), failed]);
  return {
    init: () => call("init"),
    filters: () => call("filters"),
    options: (settings) => call("options", settings),
    preload: (query) => call("preload", query),
    search: async (query, options) => {
      const response = await call<{ results: { id: string }[]; filters?: Record<string, Record<string, number>> }>("search", query, options);
      return { ...response, results: response.results.map(({ id }) => ({ id, data: () => recordOf(id) })) };
    },
  };
}

const preloaded = new Set<string>();
let preloading: Promise<void> = Promise.resolve();

/**
 * Pagefind 1.4 stores the last word of each index chunk shortened ("beguinag"), so a longer word such as
 * "beguinages" sorts between two chunks. Pagefind then loads neither, falls back to a short prefix ("b") and
 * returns tens of thousands of hits; once the right chunk is in memory, the word is found. 788 words were
 * affected (abbaye, travaux, Tollebeek …). Preloading the chunks of each word's shorter prefixes puts that
 * chunk in memory first. A word also matches the longer words it begins with, and Pagefind loads only the chunk of
 * the word itself: "abbaye" ends one chunk and "abbayes" begins the next, which halved the hits (2,477 of 4,515). The
 * word with "zz" after it sorts after those longer words, so its chunk is loaded too. Pagefind 1.5 fixes this, but
 * also makes every metadata field searchable.
 */
function loadPrefixChunks(pagefind: Pagefind, query: string): Promise<void> {
  const prefixes: string[] = [];
  for (const word of query.toLowerCase().split(/\s+/)) {
    // A field word ("au_vanthemse") stops at its tag and two letters: "au" or "au_" would load the chunks of every
    // author name, about ten in a row before an author search.
    const shortest = /^[a-z]{2}_/.test(word) ? 5 : 2;
    if (word.length >= shortest && !preloaded.has(`${word}zz`)) {
      preloaded.add(`${word}zz`);
      prefixes.push(`${word}zz`);
    }
    for (let size = word.length - 1; size >= shortest; size -= 1) {
      const prefix = word.slice(0, size);
      if (!preloaded.has(prefix)) {
        preloaded.add(prefix);
        prefixes.push(prefix);
      }
    }
  }
  // One preload at a time: two searches run side by side for optional function words.
  preloading = preloading.then(async () => {
    for (const prefix of prefixes) await pagefind.preload(prefix);
  });
  return preloading;
}

export function foldQuery(query: string): string {
  return query.normalize("NFD").replace(/\p{M}/gu, "");
}

export type SearchField = "all" | "author" | "title" | "host" | "series";

/** One word of a query as an index word: whole (``tag_word_``, the index's closing "_") or, with ``prefix``, every word it begins. */
function indexWord(tag: string, word: string, prefix: boolean): string {
  return prefix ? `${tag}_${word}` : `${tag}_${word}_`;
}

/**
 * The query as Pagefind words. Every word is matched whole (the index closes each with "_"): "Brugge" does not
 * find "bruggen". A word ending in "*", or every word when ``prefix`` is set (the switch "also words that begin
 * with"), finds the longer words it begins. A leading hyphen is Pagefind’s “exclude this word”, so Anne-Laure would
 * drop every Laure: hyphens split words. Without ``translations``, all text and title search the record's own words.
 */
export function searchQuery(query: string, field: SearchField = "all", translations = true, prefix = false): string {
  // An author searched by the name as the author row writes it: that person, as one word (``personWord``).
  const name = field === "author" ? personName(query) : null;
  if (name) return personWord(name[0], name[1]);
  if (field === "author") return nameWords(query).map(({ word, prefix: open }) => indexWord("au", word, open || prefix)).join(" ");
  const tag = fieldTag(field, translations);
  // A function word ("de", "la") stays whole: as a prefix it would match thousands of words, for nothing.
  return queryWords(query).map(({ word, prefix: open }) => indexWord(tag, word, open || (prefix && !FUNCTION_WORDS.has(word)))).join(" ");
}

/** The index tag a search of ``field`` asks for (scripts/build-index.mjs). */
export function fieldTag(field: SearchField, translations: boolean): string {
  if (field === "all") return translations ? "aw" : "og";
  if (field === "title") return translations ? "ti" : "ot";
  if (field === "author") return "au";
  return field === "series" ? "se" : "in";
}

/** The words of a text query, folded, with a trailing "*" read as "every word it begins". */
export function queryWords(query: string): { word: string; prefix: boolean }[] {
  return foldQuery(query)
    .toLowerCase()
    .split(/[\s\-–—'’]+/)
    .flatMap((raw) => {
      const star = /\*$/.test(raw);
      // One letter ("l'abbaye", an initial) is no index word: the index keeps words of two letters or more.
      return (raw.match(/[\p{L}\p{N}]+/gu) || [])
        .map((word, index, all) => ({ word, prefix: star && index === all.length - 1 }))
        .filter((item) => item.word.length > 1);
    });
}

/**
 * Function words of French, Dutch, English, German and Latin, accent-folded. A title may say “Guibert of
 * Gembloux” where the reader typed “de”, so these words are optional: they order the hits but do not exclude any.
 */
const FUNCTION_WORDS = new Set(
  [
    "a au aux avec dans de des du en entre et la le les ou par pour sous sur un une",
    "aan bij de den der des door een en het in met naar of op over te ten ter tot uit van voor",
    "a an and at by for from in of on or the to with",
    "auf aus bei das dem den der des die ein eine einer eines fur im mit oder und vom von zu zum zur",
    "ad cum et in per",
  ]
    .join(" ")
    .split(" "),
);

/** The function words, for the page's notices. */
export const FUNCTION_WORD_SET: ReadonlySet<string> = FUNCTION_WORDS;

/**
 * The query without its function words, or null when nothing would change. An author search keeps them, since
 * de, van and le belong to the surname; so does a quoted query, and one made only of function words.
 */
export function relaxedQuery(query: string, field: SearchField = "all", translations = true, prefix = false): string | null {
  if (field === "author" || query.includes('"')) return null;
  const words = foldQuery(query).toLowerCase().replace(/-/g, " ").split(/\s+/).filter(Boolean);
  const kept = words.filter((word) => !FUNCTION_WORDS.has(word));
  if (kept.length === 0 || kept.length === words.length) return null;
  return searchQuery(kept.join(" "), field, translations, prefix);
}

/**
 * The longer index words a whole-word search leaves out, per query word ("brugge" → bruggen, brugges …), the
 * shortest first: the result says so and offers them (the reviewer's "bruggen" for Brugge, 9 Nov 2026). ``tag`` is the
 * Pagefind tag of the search ("aw", "au" …). Only words of letters, of three letters or more, are looked up.
 */
export async function longerWords(words: string[], tag: string, limit = 6): Promise<{ word: string; longer: string[]; more: number }[]> {
  const found: { word: string; longer: string[]; more: number }[] = [];
  for (const word of words) {
    if (word.length < 3 || !/^\p{L}+$/u.test(word)) continue;
    const token = `${tag}_${word}`;
    const list = await knownFile(token.slice(0, 5));
    if (!list) continue;
    const all: string[] = [];
    for (let low = lowerBound(list, token); low < list.length && list[low].startsWith(token); low += 1) {
      const candidate = list[low].slice(3).replace(/_$/, "");
      if (candidate !== word && list[low].endsWith("_")) all.push(candidate);
    }
    // The nearest forms first ("bruggen", "brugges" before "bruggehooft"): the shortest, then in order.
    const longer = [...all].sort((a, b) => a.length - b.length || (a < b ? -1 : 1)).slice(0, limit);
    if (all.length) found.push({ word, longer, more: all.length - longer.length });
  }
  return found;
}

function lowerBound(list: string[], token: string): number {
  let low = 0;
  let high = list.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (list[middle] < token) low = middle + 1;
    else high = middle;
  }
  return low;
}

/** The words a search under ``tag`` ("aw", "og", "ti" …, ``fieldTag``) finds in a record. */
export function indexWords(words: IndexWords | undefined, tag: string): string[] {
  const list = (value?: string) => (value ? value.split(" ") : []);
  if (!words) return [];
  if (tag === "og") return list(words.og);
  if (tag === "aw") return [...list(words.og), ...list(words.tw)];
  if (tag === "ot") return list(words.ot);
  if (tag === "ti") return [...list(words.ot), ...list(words.tt)];
  return list(words[tag as keyof IndexWords]);
}

function wordsOf(text: string): string[] {
  return foldQuery(text).toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
}

/**
 * Whether a hit was found only through the machine translation of its title: a word of the query (or, with
 * ``prefix``, a word that begins with it) is among the translations' new words but nowhere in the record's own text.
 */
export function foundThroughTranslation(words: IndexWords | undefined, query: string, prefix = false): boolean {
  if (!words?.tw) return false;
  const own = indexWords(words, "og");
  const translated = indexWords(words, "aw").slice(own.length);
  const has = (list: string[], word: string) => list.some((candidate) => (prefix ? candidate.startsWith(word) : candidate === word));
  return wordsOf(query)
    .filter((word) => word.length > 2 && !FUNCTION_WORDS.has(word))
    .some((word) => !has(own, word) && has(translated, word));
}

type WordFile = { counts: Record<string, [number, string?]>; keys: string[] };
const knownFiles = new Map<string, Promise<string[] | null>>();

/** The indexed words beginning with ``key`` (sorted), [] when there are none, or null when the file cannot be read. */
function knownFile(key: string): Promise<string[] | null> {
  if (!knownFiles.has(key)) {
    const url = new URL(`${import.meta.env.BASE_URL}known/${key}.txt`, document.baseURI).href;
    knownFiles.set(
      key,
      fetch(url)
        .then((response) => (response.ok ? response.text().then((text) => (text ? text.split("\n") : [])) : response.status === 404 ? [] : null))
        .catch(() => null),
    );
  }
  return knownFiles.get(key)!;
}

/**
 * The words of a Pagefind query that are not in the index: a whole word ("aw_brugge_") that no index word equals, or
 * a prefix ("aw_brugg") that no index word begins. Pagefind 1.4, once the prefix chunks are loaded, answers such a
 * word with every word that shares its prefix (16,638 slow hits for an author "vanthemse"), so a query holding one
 * finds nothing and is not run. Only words of four letters or more are checked, bare or with a field tag
 * ("au_vanthemse"); anything else, and any word whose list cannot be read, counts as known.
 */
export async function unknownWords(query: string): Promise<string[]> {
  const unknown: string[] = [];
  for (const token of query.toLowerCase().split(/\s+/).filter(Boolean)) {
    const tagged = /^[a-z]{2}_/.test(token);
    const whole = token.endsWith("_");
    const word = (tagged ? token.slice(3) : token).replace(/_$/, "");
    if (word.length < 4 || !/^\p{L}+$/u.test(word)) continue;
    const list = await knownFile(tagged ? token.slice(0, 5) : token.slice(0, 3));
    if (list === null) continue;
    const low = lowerBound(list, token);
    const found = whole ? low < list.length && list[low] === token : low < list.length && list[low].startsWith(token);
    if (!found) unknown.push(token);
  }
  return unknown;
}

const wordFiles = new Map<string, Promise<WordFile>>();

/** Words of the bibliography whose first two letters are ``shard``, with their number of entries. */
function wordFile(shard: string): Promise<WordFile> {
  if (!wordFiles.has(shard)) {
    const url = new URL(`${import.meta.env.BASE_URL}words/${shard}.json`, document.baseURI).href;
    wordFiles.set(
      shard,
      fetch(url)
        .then((response) => (response.ok ? response.json() : {}))
        .catch(() => ({}))
        .then((counts: Record<string, [number, string?]>) => ({ counts, keys: Object.keys(counts) })),
    );
  }
  return wordFiles.get(shard)!;
}

/** Edits between two words (insert, delete, replace, swap two neighbours), or ``limit + 1`` once it is exceeded. */
export function editDistance(left: string, right: string, limit: number): number {
  if (Math.abs(left.length - right.length) > limit) return limit + 1;
  let before: number[] = [];
  let previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let row = 1; row <= left.length; row += 1) {
    const current = [row];
    let best = row;
    for (let column = 1; column <= right.length; column += 1) {
      const cost = left[row - 1] === right[column - 1] ? 0 : 1;
      let value = Math.min(previous[column] + 1, current[column - 1] + 1, previous[column - 1] + cost);
      if (row > 1 && column > 1 && left[row - 1] === right[column - 2] && left[row - 2] === right[column - 1]) {
        value = Math.min(value, before[column - 2] + 1);
      }
      current.push(value);
      best = Math.min(best, value);
    }
    if (best > limit) return limit + 1;
    before = previous;
    previous = current;
  }
  return previous[right.length];
}

/**
 * "Did you mean …?": for each query word that occurs nowhere in the bibliography, the closest word that does
 * (one edit for short words, two from eight letters), the most frequent first. Only the small file for the
 * word's first two letters is fetched, after the results are shown.
 */
export async function spellingSuggestions(query: string, prefix = false): Promise<{ word: string; suggestion: string; count: number }[]> {
  const found: { word: string; suggestion: string; count: number }[] = [];
  for (const word of contentWords(query).map((item) => item.replace(/['’*]/g, ""))) {
    if (word.length < 4 || /\d/.test(word)) continue;
    const file = await wordFile(/^[a-z]{2}/.test(word) ? word.slice(0, 2) : "_");
    if (file.counts[word] || (prefix && file.keys.some((key) => key.startsWith(word)))) continue;
    const limit = word.length >= 8 ? 2 : 1;
    let best: { key: string; distance: number; count: number } | null = null;
    for (const key of file.keys) {
      const distance = editDistance(word, key, limit);
      if (distance > limit) continue;
      const count = file.counts[key][0];
      if (!best || distance < best.distance || (distance === best.distance && count > best.count)) best = { key, distance, count };
    }
    if (best) found.push({ word, suggestion: file.counts[best.key][1] || best.key, count: best.count });
  }
  return found;
}

/** The words of a query that carry meaning: folded, lower case, without function words. */
export function contentWords(query: string): string[] {
  return foldQuery(query).toLowerCase().split(/[^\p{L}\p{N}]+/u).filter((word) => word.length > 1 && !FUNCTION_WORDS.has(word));
}

/**
 * Related by meaning (trial): the stored neighbours of the first hits, ranked by the sum of their scores, with
 * the first hits weighing more. With five hits or more, a title must come back from at least two of them, so
 * one stray hit does not pull the list off subject. Titles that hold every query word are left out: the keyword
 * search lists them already. Nothing new is downloaded except the records shown.
 */
export async function relatedByMeaning(
  pagefind: Pagefind,
  top: Hit[],
  query: string,
  known: (id: string) => Hit | null,
  limit = 10,
): Promise<Hit[]> {
  const shown = new Set(top.map((hit) => hit.meta.id));
  const votes = new Map<string, { score: number; hits: number }>();
  top.forEach((hit, rank) => {
    for (const { id, score } of similarOf(hit.meta)) {
      if (shown.has(id)) continue;
      const vote = votes.get(id) || { score: 0, hits: 0 };
      votes.set(id, { score: vote.score + score / (1 + rank / 10), hits: vote.hits + 1 });
    }
  });
  const needed = top.length >= 5 ? 2 : 1;
  const ranked = [...votes]
    .filter(([, vote]) => vote.hits >= needed)
    .sort((a, b) => b[1].score - a[1].score)
    .slice(0, limit * 2)
    .map(([id]) => id);
  const loaded = await Promise.all(ranked.map(async (id) => known(id) || (await findRecord(pagefind, id))));
  const words = contentWords(query);
  return loaded
    .filter((hit): hit is Hit => hit !== null)
    .filter((hit) => {
      const text = contentWords(`${hit.meta.citation || ""} ${hit.meta.title || ""}`);
      return !words.every((word) => text.includes(word));
    })
    .slice(0, limit);
}

/**
 * The share of an all-text search's hits on which its words are a name of the entry's authors or editors, from
 * which those entries come first. On the build of 10 Nov 2026 a surname is an author word on 44–90 % of the entries
 * that hold it (Pirenne 44 %, Vanthemsche 57 %, Janssens 83 %), a town, a king or a word under 15 % (Gent and
 * Brugge under 1 %, Bisschop 2 %, Leopold 14 %), so "Gent" keeps its order and "Vanthemsche" lists his own work
 * before the chapters of the volumes he edited (plan §4f, point 8).
 */
export const AUTHOR_SHARE = 0.25;

/**
 * The query as a search of the people's words, whole (``au_vanthemsche_``), as the author field reads it (particles
 * joined), or null when it is no name: a quoted phrase, a "*", or only particles.
 */
export function authorQuery(query: string): string | null {
  if (/["*]/.test(query)) return null;
  const words = nameWords(query).filter((item) => !item.prefix);
  return words.length ? words.map(({ word }) => indexWord("au", word, false)).join(" ") : null;
}

/**
 * ``results`` with the hits in ``authored`` first, each part in its own order, when they are at least
 * ``AUTHOR_SHARE`` of them (and at least two); else null, and the order stays.
 */
export function authorsFirst<T extends { id: string }>(results: T[], authored: ReadonlySet<string>): T[] | null {
  const first = results.filter((result) => authored.has(result.id));
  if (first.length < 2 || first.length < AUTHOR_SHARE * results.length || first.length === results.length) return null;
  return [...first, ...results.filter((result) => !authored.has(result.id))];
}

/** Above this many hits the strict search is skipped: it is the slow one, since a function word ("de", "la") is
 * on most entries, and among thousands of hits its ordering adds little. */
export const STRICT_LIMIT = 2000;

/**
 * Every word must match in Pagefind, so a search runs twice, as an engine with optional terms would rank it: the
 * hits with all the words first, in their own order, then the hits that miss only function words. The looser
 * search holds both, so its filter counts are the counts of the merged list. A sorted list is the looser one; so is
 * a list of more than ``STRICT_LIMIT`` hits.
 */
export async function searchBoth(
  pagefind: Pagefind,
  strict: string | null,
  loose: string | null,
  options: { filters?: Filters; sort?: Record<string, "asc" | "desc"> },
  current: () => boolean = () => true,
): Promise<SearchResponse> {
  if (!loose || loose === strict) return pagefind.search(strict, options);
  const more = await pagefind.search(loose, options);
  // A search no longer wanted (another began) does not start its second half: the worker computes one at a time.
  if (options.sort || more.results.length > STRICT_LIMIT || !current()) return more;
  const all = await pagefind.search(strict, options);
  const first = new Set(all.results.map((result) => result.id));
  return { results: [...all.results, ...more.results.filter((result) => !first.has(result.id))], filters: more.filters };
}

/** No hits, with every filter value counted zero, so the filter column keeps its values. */
export async function nothingFound(pagefind: Pagefind): Promise<SearchResponse> {
  const all = await pagefind.filters();
  return {
    results: [],
    filters: Object.fromEntries(Object.entries(all).map(([key, values]) => [key, Object.fromEntries(Object.keys(values).map((value) => [value, 0]))])),
  };
}

export async function findRecord(pagefind: Pagefind, id: string): Promise<Hit | null> {
  const direct = await pagefind.search(foldQuery(id));
  const found = await match(direct, id);
  if (found) return found;
  const printed = id.match(/^bhb:(\d{4})-(.+)$/);
  if (!printed) return null;
  const response = await pagefind.search(printed[2], { filters: { year: [printed[1]] } });
  return match(response, id);
}

/** The entry with this id; else the entry that lists the same publication under it; else the one that had it before
 * (a repaired printed number), so old links still work. The entry that holds the id now comes first. */
async function match(response: SearchResponse, id: string): Promise<Hit | null> {
  let listed: Hit | null = null;
  let former: Hit | null = null;
  for (const result of response.results.slice(0, 40)) {
    const data = await result.data();
    if (data.meta.id === id) return data;
    // The same publication listed again in another volume: that listing's id is an id of now, and wins over an
    // id another entry had in an earlier release.
    if (!listed && (data.meta.listedIds || "").split("|").includes(id)) listed = data;
    if (!former && (data.meta.formerIds || "").split("|").includes(id)) former = data;
  }
  return listed || former;
}
