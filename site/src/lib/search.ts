export interface Hit {
  url: string;
  excerpt: string;
  meta: {
    id: string;
    title: string;
    citation: string;
    year: string;
    number: string;
    section: string;
    source?: string;
    categoryFr?: string;
    categoryNl?: string;
    categoryEn?: string;
    categoryTheme?: string;
    categoryDraft?: string;
    categoryMachine?: string;
    categorySource?: string;
    authors?: string;
    editors?: string;
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
    inVolume?: string;
    extent?: string;
    seriesTitle?: string;
    seriesNumber?: string;
    kind?: string;
    themes?: string;
    specificFr?: string;
    specificNl?: string;
    specificEn?: string;
    specificFrom?: string;
    specificMachine?: string;
    themesSuggested?: string;
    periods?: string;
    periodsSuggested?: string;
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

/** Drop host editors that the index still repeats among the chapter’s authors. */
export function authorsWithout(authors: string | undefined, editors: string): string | undefined {
  if (!authors) return authors;
  if (!editors) return authors;
  const drop = new Set(splitNames(editors));
  const kept = splitNames(authors).filter((name) => !drop.has(name));
  if (kept.length === 0) return undefined;
  return joinNames(kept);
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

/** Journal and monograph titles (and their subtitles) are italic; an article or chapter title and subtitle stay roman. */
export function citationHtml(
  citation: string,
  meta: { title?: string; subtitle?: string; host?: string; hostSubtitle?: string; kind?: string; pubyear?: string; yearMachine?: string; inVolume?: string },
  yearNote = "",
  volumeNote = "",
): string {
  const shown = withHostYear(presentCitation(citation || ""), meta.pubyear, meta.yearMachine);
  let html = escapeHtml(shown);
  if (meta.inVolume) html = withVolume(html, meta.inVolume, meta.host, volumeNote);
  if (meta.yearMachine === "1" && meta.pubyear && yearIn(shown, meta.pubyear)) {
    const note = escapeHtml(yearNote);
    html = html.replace(meta.pubyear, `<span class="derived" title="${note}">${meta.pubyear}</span>`);
  }
  // The book's title and subtitle are italic wherever they stand after "In:", also after its editors
  // ("In: Deploige (Jeroen), Deneckere (Gita). Mystifying the Monarch").
  // A journal title stands after the article's title, without "In:".
  const titleAt = meta.title ? html.indexOf(escapeHtml(meta.title.trim())) : -1;
  const after = html.search(/In:/) >= 0 ? html.search(/In:/) : meta.kind === "article" && titleAt >= 0 ? titleAt + escapeHtml(meta.title!.trim()).length : -1;
  if (after >= 0 && !meta.inVolume) {
    for (const part of [meta.host, meta.hostSubtitle]) {
      const safe = escapeHtml(part?.trim() || "");
      const at = safe ? html.indexOf(safe, after) : -1;
      if (at >= 0) html = `${html.slice(0, at)}<em>${safe}</em>${html.slice(at + safe.length)}`;
    }
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

function escapeHtml(value: string): string {
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
  options: (settings: { ranking?: { pageLength?: number } }) => Promise<void>;
  preload: (query: string) => Promise<void>;
}

/** Pagefind favours short records (default 0.75), so a short stub could outrank the work it points to.
 * 0.4 kept the top hits of test queries or improved them; 0.1 let long entries such as volumes with
 * their contents take over. */
const PAGE_LENGTH_WEIGHT = 0.4;

let engine: Pagefind | null = null;

export async function loadEngine(): Promise<Pagefind> {
  if (engine) return engine;
  const importer = new Function("url", "return import(url)") as (url: string) => Promise<Pagefind>;
  // Resolve against the page, not the bundle. A relative import from /assets/
  // would request /assets/pagefind/, where the index is not deployed.
  const loaded = await importer(new URL(`${import.meta.env.BASE_URL}pagefind/pagefind.js`, document.baseURI).href);
  await loaded.options({ ranking: { pageLength: PAGE_LENGTH_WEIGHT } });
  await loaded.init();
  await loaded.filters();
  engine = { ...loaded, search: async (query, options) => {
    if (query) await loadPrefixChunks(loaded, query);
    return loaded.search(query, options);
  } };
  return engine;
}

const preloaded = new Set<string>();
let preloading: Promise<void> = Promise.resolve();

/**
 * Pagefind 1.4 stores the last word of each index chunk shortened ("beguinag"), so a longer word such as
 * "beguinages" sorts between two chunks. Pagefind then loads neither, falls back to a short prefix ("b") and
 * returns tens of thousands of hits; once the right chunk is in memory, the word is found. 788 words were
 * affected (abbaye, travaux, Tollebeek …). Preloading the chunks of each word's shorter prefixes puts that
 * chunk in memory first. Pagefind 1.5 fixes this, but also makes every metadata field searchable.
 */
function loadPrefixChunks(pagefind: Pagefind, query: string): Promise<void> {
  const prefixes: string[] = [];
  for (const word of query.toLowerCase().split(/\s+/)) {
    for (let size = word.length - 1; size >= 2; size -= 1) {
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

export type SearchField = "all" | "author" | "title" | "host";

/** A leading hyphen is Pagefind’s “exclude this word”, so Anne-Laure would drop every Laure. */
export function searchQuery(query: string, field: SearchField = "all"): string {
  const words = foldQuery(query).replace(/-/g, " ").split(/\s+/).filter(Boolean);
  if (field === "all") return words.join(" ");
  const tag = field === "author" ? "au" : field === "title" ? "ti" : "in";
  return words.map((word) => `${tag}_${word}`).join(" ");
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

/**
 * The query without its function words, or null when nothing would change. An author search keeps them, since
 * de, van and le belong to the surname; so does a quoted query, and one made only of function words.
 */
export function relaxedQuery(query: string, field: SearchField = "all"): string | null {
  if (field === "author" || query.includes('"')) return null;
  const words = foldQuery(query).toLowerCase().replace(/-/g, " ").split(/\s+/).filter(Boolean);
  const kept = words.filter((word) => !FUNCTION_WORDS.has(word));
  if (kept.length === 0 || kept.length === words.length) return null;
  return searchQuery(kept.join(" "), field);
}

type WordFile = { counts: Record<string, [number, string?]>; keys: string[] };
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
export async function spellingSuggestions(query: string): Promise<{ word: string; suggestion: string; count: number }[]> {
  const found: { word: string; suggestion: string; count: number }[] = [];
  for (const word of contentWords(query).map((item) => item.replace(/['’]/g, ""))) {
    if (word.length < 4 || /\d/.test(word)) continue;
    const file = await wordFile(/^[a-z]{2}/.test(word) ? word.slice(0, 2) : "_");
    if (file.counts[word] || file.keys.some((key) => key.startsWith(word))) continue;
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
 * Every word must match in Pagefind, so a search runs twice, as an engine with optional terms would rank it: the
 * hits with all the words first, in their own order, then the hits that miss only function words. The looser
 * search holds both, so its filter counts are the counts of the merged list. A sorted list is the looser one.
 */
export async function searchBoth(
  pagefind: Pagefind,
  strict: string | null,
  loose: string | null,
  options: { filters?: Filters; sort?: Record<string, "asc" | "desc"> },
): Promise<SearchResponse> {
  if (!loose || loose === strict) return pagefind.search(strict, options);
  const [all, more] = await Promise.all([pagefind.search(strict, options), pagefind.search(loose, options)]);
  if (options.sort) return more;
  const first = new Set(all.results.map((result) => result.id));
  return { results: [...all.results, ...more.results.filter((result) => !first.has(result.id))], filters: more.filters };
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

async function match(response: SearchResponse, id: string): Promise<Hit | null> {
  for (const result of response.results.slice(0, 40)) {
    const data = await result.data();
    if (data.meta.id === id) return data;
  }
  return null;
}
