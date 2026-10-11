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
    authors?: string;
    subtitle?: string;
    host?: string;
    hostSubtitle?: string;
    hostEditors?: string;
    volume?: string;
    issue?: string;
    pages?: string;
    pubyear?: string;
    place?: string;
    publisher?: string;
    extent?: string;
    kind?: string;
  };
}

/** A printed “Cfr. / Voir / Zie n°” points at another entry in the same volume. */
const CROSS_REF =
  /\s*\[?\s*(?:cfr|voir|zie)\.?\s+n(?:°|º|o|r)\.?\s*(?:\d{2,6}(?:\s*(?:bis|ter|quater))?(?:\s*[,;]\s*|\s+(?:et|en|and)\s+)?)+\]?/gi;

/** The catalogue line we compose sometimes ends with "p.." and writes "In :". Cross-references to the printed volume are left out. */
export function presentCitation(text: string): string {
  return text
    .replaceAll("In :", "In:")
    .replace(CROSS_REF, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([.,])/g, "$1")
    .replace(/\.{2,}(?=\s*$)/g, ".")
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

/** Journal and monograph titles are italic; an article or chapter title stays roman. A subtitle is italic in the citation line. */
export function citationHtml(citation: string, meta: { title?: string; subtitle?: string; host?: string; kind?: string }): string {
  let html = escapeHtml(presentCitation(citation || ""));
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
  results: { data: () => Promise<Hit> }[];
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
  const loaded = await importer(`${import.meta.env.BASE_URL}pagefind/pagefind.js`);
  await loaded.init();
  await loaded.filters();
  engine = loaded;
  return loaded;
}

export function foldQuery(query: string): string {
  return query.normalize("NFD").replace(/\p{M}/gu, "");
}

/** A leading hyphen is Pagefind’s “exclude this word”, so Anne-Laure would drop every Laure. */
export function searchQuery(query: string): string {
  return foldQuery(query).replace(/-/g, " ");
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
