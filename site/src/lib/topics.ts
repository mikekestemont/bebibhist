// The topic map's data, shared by the build script (scripts/build-topics.mjs) and the page (TopicMap.svelte).
//
// public/topics/points.bin holds one column after the other, each as long as there are points: x and y as
// Uint16 (the unit square times 65535), the publication year as Uint8 (years since 1800; 0 = unknown), the
// subject areas and the periods as Uint8 bit sets, and the finest region as Uint16. The points are in a fixed
// random order, so that drawing them one after the other never paints a region on top of another.
// public/topics/cells/<k>.json holds the titles of finest region k; public/topics/words/<ab>.json the points
// whose title, translations or authors have a word that begins with "ab".

export const THEMES = ["local", "political", "economic", "social", "religious", "cultural", "reference", "general"] as const;
export const PERIODS = ["general", "ancient", "medieval", "burgundian", "early-modern", "contemporary"] as const;
export const YEAR_BASE = 1800;

export type Region = {
  id: string;
  level: number;
  parent: string | null;
  x: number;
  y: number;
  n: number;
  name?: { nl: string; fr: string; en: string };
};

export type Points = {
  n: number;
  x: Float32Array;
  y: Float32Array;
  year: Uint8Array;
  theme: Uint8Array;
  period: Uint8Array;
  cell: Uint16Array;
};

/** A cell's titles: [point index, record id, title, authors, year, translations (nl, fr, en; "" when none)]. */
export type CellTitle = [number, string, string, string, string, string, string, string];

/** Function words of the four languages, left out of the word index and of a query. */
export const STOP = new Set(
  `de het een en van in op te voor met aan bij uit over door tot als om naar of
  le la les l d des du un une et en au aux a dans sur par pour avec sous entre
  the of and in on at to for from by with an as or
  der die das und im zu von den dem des ein eine`.split(/\s+/),
);

export function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** The words of a text, folded, without function words and one-letter words. */
export function tokens(text: string): string[] {
  return fold(text).split(/[^a-z0-9]+/).filter((word) => word.length > 1 && !STOP.has(word));
}

/** The file of the word index that holds the words beginning like ``word``. */
export function shardOf(word: string): string {
  return word.slice(0, 2).padEnd(2, "_");
}

export function decodePoints(buffer: ArrayBuffer): Points {
  const n = new Uint32Array(buffer, 0, 1)[0];
  let at = 4;
  const take = <T>(make: (b: ArrayBuffer, o: number, l: number) => T, bytes: number): T => {
    const out = make(buffer, at, n);
    at += n * bytes;
    return out;
  };
  const rawX = take((b, o, l) => new Uint16Array(b, o, l), 2);
  const rawY = take((b, o, l) => new Uint16Array(b, o, l), 2);
  const year = take((b, o, l) => new Uint8Array(b, o, l), 1);
  const theme = take((b, o, l) => new Uint8Array(b, o, l), 1);
  const period = take((b, o, l) => new Uint8Array(b, o, l), 1);
  // The cells column starts on an even byte.
  at += at % 2;
  const cell = take((b, o, l) => new Uint16Array(b, o, l), 2);
  const x = new Float32Array(n);
  const y = new Float32Array(n);
  for (let i = 0; i < n; i += 1) {
    x[i] = rawX[i] / 65535;
    y[i] = rawY[i] / 65535;
  }
  return { n, x, y, year, theme, period, cell };
}

/** Delta-coded point lists, as the word index stores them, back to point indices. */
export function undelta(list: number[]): number[] {
  const out = new Array(list.length);
  let at = 0;
  for (let i = 0; i < list.length; i += 1) {
    at += list[i];
    out[i] = at;
  }
  return out;
}

/** The points whose words begin with every word of the query; null for a query without words. */
export function matchQuery(query: string, shards: Map<string, Record<string, number[]>>): Set<number> | null {
  const words = tokens(query);
  if (!words.length) return null;
  let found: Set<number> | null = null;
  for (const word of words) {
    const shard = shards.get(shardOf(word)) || {};
    const hits = new Set<number>();
    for (const [key, list] of Object.entries(shard)) {
      if (key.startsWith(word)) for (const point of undelta(list)) hits.add(point);
    }
    found = found ? new Set([...found].filter((point) => hits.has(point))) : hits;
    if (!found.size) break;
  }
  return found;
}
