// Pagefind's filters, sort orders and filter counts, read from the files of its index and computed here instead of in
// Pagefind. Pagefind 1.4 counts every value of every filter on every search by looking each of its entries up in the
// list of hits, one hit after the other, twice (``get_filters`` in pagefind_web/src/filter.rs): with 1.3 million
// filter entries that is 0.9 ms a hit, 10.6 s for a subject of 12,000 entries whose hits it finds in 0.1 s (24 Nov
// 2026). It also looks each hit up in a sort order entry by entry (1 s for the same subject). Pagefind counts only the
// filters it has loaded, so the page lets it load none: it ranks the hits, and everything else is done here.

/** A list of values means "all of them", as in Pagefind; `{ any: [...] }` means "one of them" (a range of years). */
export type Filters = Record<string, string[] | { any: string[] }>;

export type Sort = Record<string, "asc" | "desc">;

/** The number of hits with each value of each filter, zeros included. */
export type FilterCounts = Record<string, Record<string, number>>;

/** Filter value → the numbers of its pages (records), as a filter file lists them. */
export type FilterValues = Map<string, Uint32Array>;

export interface IndexMeta {
  /** The id of each page, by its number: the order in which the records were indexed. */
  ids: string[];
  /** Filter name → the name of its file. */
  filterFiles: Map<string, string>;
  /** Sort key → the place of each page in that order (by page number); ``UNSORTED`` for a page without the key. */
  ranks: Map<string, Uint32Array>;
}

const UNSORTED = 0xffffffff;

/** The parts of CBOR that Pagefind's files use: texts, lists and whole numbers. */
class Reader {
  private at = 0;
  private bytes: Uint8Array;

  constructor(bytes: Uint8Array) {
    this.bytes = bytes;
  }

  private head(major: number): number {
    const byte = this.bytes[this.at++];
    if (byte >> 5 !== major) throw new Error(`search index: unexpected byte ${byte} at ${this.at - 1}`);
    const info = byte & 31;
    if (info < 24) return info;
    if (info > 26) throw new Error(`search index: unexpected byte ${byte} at ${this.at - 1}`);
    let value = 0;
    for (let size = 1 << (info - 24); size > 0; size -= 1) value = value * 256 + this.bytes[this.at++];
    return value;
  }

  /** The length of a list that begins here. */
  list(): number {
    return this.head(4);
  }

  number(): number {
    return this.head(0);
  }

  numbers(): Uint32Array {
    return Uint32Array.from({ length: this.list() }, () => this.number());
  }

  text(): string {
    const length = this.head(3);
    const end = this.at + length;
    let plain = "";
    // Ids and filter values are short and plain: a decoder call for each of 240,000 ids is slower than this.
    for (let at = this.at; at < end; at += 1) {
      if (this.bytes[at] > 127) {
        plain = new TextDecoder().decode(this.bytes.subarray(this.at, end));
        break;
      }
      plain += String.fromCharCode(this.bytes[at]);
    }
    this.at = end;
    return plain;
  }

  skipText(): void {
    const length = this.head(3);
    this.at += length;
  }
}

/** pagefind.*.pf_meta: [version, [[id, words]], [[from, to, file]], [[filter, file]], [[sort key, [page]]]]. */
export function readMeta(bytes: Uint8Array): IndexMeta {
  const reader = new Reader(bytes);
  reader.list();
  reader.skipText();
  const ids = Array.from({ length: reader.list() }, () => {
    reader.list();
    const id = reader.text();
    reader.number();
    return id;
  });
  for (let left = reader.list(); left > 0; left -= 1) {
    reader.list();
    for (let part = 0; part < 3; part += 1) reader.skipText();
  }
  const filterFiles = new Map<string, string>();
  for (let left = reader.list(); left > 0; left -= 1) {
    reader.list();
    const name = reader.text();
    filterFiles.set(name, reader.text());
  }
  const ranks = new Map<string, Uint32Array>();
  for (let left = reader.list(); left > 0; left -= 1) {
    reader.list();
    const key = reader.text();
    const rank = new Uint32Array(ids.length).fill(UNSORTED);
    reader.numbers().forEach((page, place) => { rank[page] = place; });
    ranks.set(key, rank);
  }
  return { ids, filterFiles, ranks };
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

/** ``pages`` in the order of a sort key; pages without the key are left out, and an unknown key changes nothing. */
export function sortPages(pages: Uint32Array, sort: Sort, ranks: Map<string, Uint32Array>): Uint32Array {
  const [key, direction] = Object.entries(sort)[0] || [];
  const rank = key ? ranks.get(key) : undefined;
  if (!rank) return pages;
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
