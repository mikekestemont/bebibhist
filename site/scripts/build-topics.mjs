// The topic map's files in public/topics/, from build/records.jsonl (``bhb topicmap apply``) and the named regions
// in data/curated/topic_regions.json. The format is described in src/lib/topics.ts.
//   node scripts/build-topics.mjs
import { createReadStream, existsSync } from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import readline from "node:readline";

import { PERIODS, THEMES, YEAR_BASE, shardOf, tokens } from "../src/lib/topics.ts";

const recordsPath = new URL("../../build/records.jsonl", import.meta.url);
const regionsPath = new URL("../../data/curated/topic_regions.json", import.meta.url);
const outputPath = new URL("../public/topics/", import.meta.url).pathname;

if (!existsSync(regionsPath)) {
  console.log("topics: no data/curated/topic_regions.json, no topic map");
  process.exit(0);
}
const { regions } = JSON.parse(await readFile(regionsPath, "utf8"));
const finest = Math.max(...regions.map((region) => region.level));
const cellIndex = new Map(regions.filter((region) => region.level === finest).map((region) => [region.id, Number(region.id.split(".")[1])]));

const placed = [];
const lines = readline.createInterface({ input: createReadStream(recordsPath, { encoding: "utf8" }), crlfDelay: Infinity });
for await (const line of lines) {
  if (!line.trim()) continue;
  const record = JSON.parse(line);
  // A listing linked to another of the same publication (``duplicate_of``) is left out, as in search, so that a
  // region's count is its search's.
  if (record.role !== "entry" || record.is_cross_listing || record.duplicate_of || record.topic_xy?.length !== 2 || !cellIndex.has(record.topic)) continue;
  placed.push(record);
}

// A fixed random order (a seeded shuffle), so the drawing order never stacks one region over another.
let seed = 7;
const random = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
for (let i = placed.length - 1; i > 0; i -= 1) {
  const j = Math.floor(random() * (i + 1));
  [placed[i], placed[j]] = [placed[j], placed[i]];
}

const n = placed.length;
const header = 4;
const evenAt = header + n * 7 + ((header + n * 7) % 2);
const buffer = new ArrayBuffer(evenAt + n * 2);
new Uint32Array(buffer, 0, 1)[0] = n;
const x = new Uint16Array(buffer, header, n);
const y = new Uint16Array(buffer, header + n * 2, n);
const year = new Uint8Array(buffer, header + n * 4, n);
const theme = new Uint8Array(buffer, header + n * 5, n);
const period = new Uint8Array(buffer, header + n * 6, n);
const cell = new Uint16Array(buffer, evenAt, n);
const cells = new Map();
const words = new Map();
placed.forEach((record, index) => {
  x[index] = Math.round(record.topic_xy[0] * 65535);
  y[index] = Math.round(record.topic_xy[1] * 65535);
  const published = publicationYear(record);
  year[index] = published ? Math.min(255, Math.max(1, published - YEAR_BASE)) : 0;
  theme[index] = bits(record.theme, THEMES);
  period[index] = bits(record.period, PERIODS);
  cell[index] = cellIndex.get(record.topic);
  const translations = record.translations || {};
  const authors = (record.persons || []).filter((person) => !["editor", "compiler", "preface", "translator", "illustrator"].includes(person.role)).map((person) => person.family).filter(Boolean);
  const row = [index, record.id, record.title || "", authors.slice(0, 3).join(", ") + (authors.length > 3 ? " …" : ""), published ? String(published) : "", translations.nl || "", translations.fr || "", translations.en || ""];
  (cells.get(cell[index]) || cells.set(cell[index], []).get(cell[index])).push(row);
  const text = [record.title, record.subtitle, record.title_translated, translations.nl, translations.fr, translations.en, authors.join(" ")].filter(Boolean).join(" ");
  for (const word of new Set(tokens(text))) {
    const shard = shardOf(word);
    const inShard = words.get(shard) || words.set(shard, new Map()).get(shard);
    (inShard.get(word) || inShard.set(word, []).get(word)).push(index);
  }
});

await rm(outputPath, { recursive: true, force: true });
await mkdir(`${outputPath}cells`, { recursive: true });
await mkdir(`${outputPath}words`, { recursive: true });
await writeFile(`${outputPath}points.bin`, new Uint8Array(buffer));
await writeFile(`${outputPath}regions.json`, JSON.stringify(regions.map(({ id, level, parent, x: rx, y: ry, n: count, name }) => ({ id, level, parent, x: rx, y: ry, n: count, name }))));
for (const [k, rows] of cells) await writeFile(`${outputPath}cells/${k}.json`, JSON.stringify(rows));
let postings = 0;
for (const [shard, inShard] of words) {
  const out = {};
  for (const [word, list] of inShard) {
    out[word] = list.map((point, i) => point - (i ? list[i - 1] : 0));
    postings += list.length;
  }
  await writeFile(`${outputPath}words/${shard}.json`, JSON.stringify(out));
}
console.log(`topics: ${n} points, ${cells.size} cells, ${words.size} word files, ${postings} postings → ${outputPath}`);

function bits(values, names) {
  let out = 0;
  for (const value of values || []) {
    const at = names.indexOf(value);
    if (at >= 0) out |= 1 << at;
  }
  return out;
}

/** The year of publication as the search filter has it (build-index.mjs, ``chronology``): the record's own from
 * 1945 on, else the volume's. */
function publicationYear(record) {
  const yearOf = (value) => Number(String(value ?? "").match(/\d{4}/)?.[0] || 0);
  const own = yearOf(record.year) || yearOf(record.host?.year);
  return own >= 1945 && own <= new Date().getFullYear() ? own : yearOf(record.bgb_year);
}
