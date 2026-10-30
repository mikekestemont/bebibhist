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
    extent?: string;
    kind?: string;
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

/** Journal and monograph titles are italic; an article or chapter title stays roman. A subtitle is italic in the citation line. */
export function citationHtml(
  citation: string,
  meta: { title?: string; subtitle?: string; host?: string; kind?: string; pubyear?: string; yearMachine?: string },
  yearNote = "",
): string {
  const shown = withHostYear(presentCitation(citation || ""), meta.pubyear, meta.yearMachine);
  let html = escapeHtml(shown);
  if (meta.yearMachine === "1" && meta.pubyear && yearIn(shown, meta.pubyear)) {
    const note = escapeHtml(yearNote);
    html = html.replace(meta.pubyear, `<span class="derived" title="${note}">${meta.pubyear}</span>`);
  }
  const host = meta.host?.trim();
  if (host) {
    const safe = escapeHtml(host);
    html = html.replace(new RegExp(`(In:\\s*)(${escapeRegExp(safe)})`), "$1<em>$2</em>");
  }
  if (meta.kind === "book" || meta.kind === "journal-issue") {
    const title = meta.title?.trim();
    if (title) html = emphasize(html, title);
  }
  const subtitle = meta.subtitle?.trim();
  if (subtitle) html = emphasize(html, subtitle);
  return html;
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

interface Pagefind {
  init: () => Promise<void>;
  filters: () => Promise<Record<string, Record<string, number>>>;
  search: (
    query: string | null,
    options?: { filters?: Record<string, string[]>; sort?: Record<string, "asc" | "desc"> },
  ) => Promise<SearchResponse>;
}

let engine: Pagefind | null = null;

export async function loadEngine(): Promise<Pagefind> {
  if (engine) return engine;
  const importer = new Function("url", "return import(url)") as (url: string) => Promise<Pagefind>;
  // Resolve against the page, not the bundle. A relative import from /assets/
  // would request /assets/pagefind/, where the index is not deployed.
  const loaded = await importer(new URL(`${import.meta.env.BASE_URL}pagefind/pagefind.js`, document.baseURI).href);
  await loaded.init();
  await loaded.filters();
  engine = loaded;
  return loaded;
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

/**
 * Every word must match in Pagefind, so a search runs twice, as an engine with optional terms would rank it: the
 * hits with all the words first, in their own order, then the hits that miss only function words. The looser
 * search holds both, so its filter counts are the counts of the merged list. A sorted list is the looser one.
 */
export async function searchBoth(
  pagefind: Pagefind,
  strict: string | null,
  loose: string | null,
  options: { filters?: Record<string, string[]>; sort?: Record<string, "asc" | "desc"> },
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
