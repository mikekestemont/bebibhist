// Pagefind's ranking, for the words that most records hold. For each hit, Pagefind 1.4 goes through the entries of all
// the words it matched (``search_term`` in pagefind_web/src/search.rs): hits times entries, 14 s for "histoire", which
// 161,805 records hold. Here each entry is read once, with the same score to the last bit; records of equal score
// follow the order of the index (Pagefind leaves them as its unstable sort does). Only a search that Pagefind would
// take long over is ranked here (``SLOW``), or one with a word in a file it cannot load (``loadable``), so every other
// search keeps its order.
import { Reader } from "./cbor.ts";

export interface Ranking {
  pageLength?: number;
  termSimilarity?: number;
}

/** A file of the index with the words from ``from`` to ``to``, both of which Pagefind stores shortened: the last word
 * is ``to`` or begins with it, and comes before ``until``, where the next file begins. */
export interface Chunk {
  from: string;
  to: string;
  until: string;
  file: string;
}

/** The entries of a word: its pages (record numbers), and the weight of the word on each. */
export interface Postings {
  word: string;
  /** The word's length in UTF-8. */
  size: number;
  pages: Uint32Array;
  weights: Uint32Array;
}

/**
 * Hits times entries above which a search is ranked here. Pagefind needs 0.27 s for this many on a fast laptop (M2 Max).
 */
export const SLOW = 500_000_000;

/**
 * The words of a query when they are all words of the index's own kind ("aw_histoire", "sc_0123456789", closed with "_"
 * or not), which Pagefind reads as they stand, else null (an entry's id).
 */
export function taggedWords(query: string): string[] | null {
  const terms = query.split(" ");
  return terms.every((term) => /^[a-z]{2}_[\p{L}\p{N}]+_?$/u.test(term) && term === term.toLowerCase()) ? terms : null;
}

/** Whether a chunk can hold a word that begins with ``term``. */
export function mayHold(chunk: Chunk, term: string): boolean {
  return chunk.until > term && (chunk.from <= term || chunk.from.startsWith(term));
}

/**
 * Whether Pagefind can load a chunk. It loads the chunk that has a word between its two ends, which it stores
 * shortened, and where the last word was shortened to less than the first ("aw_bibliothekenp" to "aw_biblioth", with
 * bibliothèque among its words) no word is: 61 chunks on 24 Nov 2026. A search for one of their words matched every
 * record and failed.
 */
export function loadable(chunk: Chunk): boolean {
  return chunk.from <= chunk.to;
}

/**
 * The words whose chunks are loaded before an entry's id is searched: its shorter beginnings, and the id with "zz",
 * which sorts after the longer ones. The last word of a chunk is stored shortened, so an id may sort between two
 * chunks, and Pagefind would load neither.
 */
export function preloads(query: string): string[] {
  const words: string[] = [];
  for (const word of query.toLowerCase().split(/\s+/)) {
    if (word.length >= 2) words.push(`${word}zz`);
    for (let size = word.length - 1; size >= 2; size -= 1) words.push(word.slice(0, size));
  }
  return words;
}

function bytesOf(text: string): number {
  return new TextEncoder().encode(text).length;
}

/** index/*.pf_index: [[[word, [[page, [location …]]]]]], a negative number giving the weight of the next locations. */
export function readChunk(bytes: Uint8Array, wanted: (word: string) => boolean): Postings[] {
  const reader = new Reader(bytes);
  const found: Postings[] = [];
  reader.list();
  for (let words = reader.list(); words > 0; words -= 1) {
    reader.list();
    const word = reader.text();
    const keep = wanted(word);
    const count = reader.list();
    const pages = new Uint32Array(keep ? count : 0);
    const weights = new Uint32Array(keep ? count : 0);
    for (let at = 0; at < count; at += 1) {
      reader.list();
      const page = reader.number();
      let weight = 25;
      let sum = 0;
      for (let locations = reader.list(); locations > 0; locations -= 1) {
        const value = reader.integer();
        if (value < 0) weight = Math.min(-value - 1, 255);
        else sum += weight;
      }
      if (keep) {
        pages[at] = page;
        weights[at] = sum;
      }
    }
    if (keep) found.push({ word, size: bytesOf(word), pages, weights });
  }
  return found;
}

const f = Math.fround;

const bits = new DataView(new ArrayBuffer(4));
function toBits(value: number): number {
  bits.setFloat32(0, value);
  return bits.getUint32(0);
}
function fromBits(value: number): number {
  bits.setUint32(0, value);
  return bits.getFloat32(0);
}

const [LG1, LG2, LG3, LG4] = [0.66666662693, 0.40000972152, 0.28498786688, 0.24279078841].map(f);

/** The natural logarithm of a normal number above zero, rounded as Pagefind's is (``logf`` of Rust's libm, from musl):
 * Math.log rounds some of them otherwise, in the last bit, and the order of the hits with them. */
export function logf(value: number): number {
  if (value === 1) return 0;
  const reduced = toBits(value) + 0x3f800000 - 0x3f3504f3;
  const k = (reduced >>> 23) - 0x7f;
  const x = f(fromBits((reduced & 0x007fffff) + 0x3f3504f3) - 1);
  const s = f(x / f(2 + x));
  const z = f(s * s);
  const w = f(z * z);
  const r = f(f(z * f(LG1 + f(w * LG3))) + f(w * f(LG2 + f(w * LG4))));
  const half = f(f(0.5 * x) * x);
  return f(f(f(f(f(s * f(half + r)) + f(k * f(9.0580006145e-6))) - half) + x) + f(k * f(6.9313812256e-1)));
}

/** e to the power of ``value``, rounded as Pagefind's is (``expf`` of Rust's libm, from musl). */
export function expf(value: number): number {
  const size = Math.abs(value);
  if (value <= -103.972084) return 0;
  if (size <= f(2 ** -14)) return f(1 + value);
  let [k, hi, lo, x] = [0, value, 0, value];
  if (toBits(size) > 0x3eb17218) {
    k = toBits(size) > 0x3f851592 ? Math.trunc(f(f(f(1.4426950216) * value) + (value < 0 ? -0.5 : 0.5))) : Math.sign(value);
    hi = f(value - f(k * f(6.9314575195e-1)));
    lo = f(k * f(1.4286067653e-6));
    x = f(hi - lo);
  }
  const square = f(x * x);
  const c = f(x - f(square * f(f(1.6666625440e-1) + f(square * f(-2.7667332906e-3)))));
  return f(f(1 + f(f(f(f(x * c) / f(2 - c)) - lo) + hi)) * 2 ** k);
}

/** The mean number of words of a record, summed as Pagefind does. */
export function averageWords(wordCounts: Uint32Array): number {
  let sum = 0;
  for (const count of wordCounts) sum = f(sum + count);
  return f(sum / wordCounts.length);
}

/** How much a word counts for a term it is ``difference`` letters longer than. */
function lengthBonus(difference: number, similarity: number): number {
  const base = expf(f(f(-0.5 * f(difference * difference)) / 4));
  return f(expf(f(base * similarity)) / expf(similarity));
}

/** The matches of a search: the entries of each term, the pages that hold them all, and Pagefind's cost. */
export interface Matches {
  terms: { term: string; entries: Postings[] }[];
  /** How many terms each page holds; a hit holds all of them. */
  held: Uint8Array;
  hits: number;
  cost: number;
}

/** The matches of ``terms`` among the words of a search's chunks. A term that begins no word leaves no hits, where
 * Pagefind takes the longest word that begins the term. */
export function matchTerms(terms: string[], words: Postings[], total: number): Matches {
  const held = new Uint8Array(total);
  let entries = 0;
  const matched = terms.map((term, at) => {
    const own = words.filter(({ word }) => word.startsWith(term));
    for (const { pages } of own) {
      entries += pages.length;
      for (const page of pages) if (held[page] === at) held[page] = at + 1;
    }
    return { term, entries: own };
  });
  let hits = 0;
  for (const count of held) hits += count === terms.length ? 1 : 0;
  return { terms: matched, held, hits, cost: hits * entries };
}

/** The pages of the matches, best first, with their scores (BM25, as in pagefind_web/src/search.rs). */
export function rankPages({ terms, held, hits }: Matches, wordCounts: Uint32Array, average: number, ranking: Ranking): { pages: Uint32Array; scores: Float32Array } {
  const k1 = f(1.4);
  const b = f(ranking.pageLength ?? 0.75);
  const similarity = f(ranking.termSimilarity ?? 1);
  const total = wordCounts.length;
  const scores = new Float32Array(total);
  // A word that several terms begin counts once, for the first of them, and double when they are two or four, as
  // Pagefind joins them.
  const words = new Map<string, { entry: Postings; term: string; times: number }>();
  for (const { term, entries } of terms) {
    for (const entry of entries) {
      const known = words.get(entry.word);
      words.set(entry.word, { entry, term: known?.term ?? term, times: (known?.times ?? 0) + 1 });
    }
  }
  // A page's word scores are added up in the order of the words.
  const inOrder = [...words.values()].sort((left, right) => (left.entry.word < right.entry.word ? -1 : 1));
  for (const { entry: { size, pages, weights }, term, times } of inOrder) {
    const bonus = lengthBonus(Math.min(size - bytesOf(term) + 1, 255), similarity);
    const idf = logf(f(f(f(f(total - pages.length) + 0.5) / f(pages.length + 0.5)) + 1));
    for (let at = 0; at < pages.length; at += 1) {
      const page = pages[at];
      if (held[page] !== terms.length || !weights[at]) continue;
      const weighted = f(f(weights[at] * (times % 2 ? 1 : 2) / 24) * bonus);
      const length = f(f(1 - b) + f(b * f(wordCounts[page] / average)));
      const frequency = f(f(f(k1 + 1) * weighted) / f(f(k1 * length) + weighted));
      scores[page] = f(scores[page] + f(idf * frequency));
    }
  }
  const order = new Uint32Array(hits);
  for (let page = 0, at = 0; page < total; page += 1) if (held[page] === terms.length) order[at++] = page;
  order.sort((left, right) => scores[right] - scores[left] || left - right);
  return { pages: order, scores };
}
