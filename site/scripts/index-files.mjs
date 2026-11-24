// The files the site reads in place of Pagefind's own, made once Pagefind has written its index:
// - pagefind.*.pf_meta, Pagefind's table, which a first search waits for. Pagefind's is 4.2 MB (24 Nov 2026), of which 2.5
//   are the sort orders and 1.1 the ids of the records. Its records get their numbers for ids, which compress, and its
//   sort orders are taken out: Pagefind is never asked to sort, and finds an index without them. 0.9 MB are left.
// - sort/*.bin, the sort orders, each read when a list is sorted by it (``loadRank`` in src/lib/searcher.ts).
// - records/*/*.bin, the records the page shows (``recordOf`` in src/lib/search.ts), in some 7,500 files instead of
//   Pagefind's one fragment per record, which are not published: GitHub Pages copies every file of a deployment, and on
//   10 Nov 2026 that copy of about 200,000 files stalled past its 10 minutes on three of eight deployments.
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, rename, rm, writeFile } from "node:fs/promises";
import { gunzipSync, gzipSync } from "node:zlib";

import { Reader } from "../src/lib/cbor.ts";
import { RECORDS_PER_FILE, readMeta } from "../src/lib/facets.ts";

const SIGNATURE = Buffer.from("pagefind_dcd");
/** In CBOR. */
const EMPTY_LIST = Buffer.from([0x80]);

/**
 * A table with the number of each record for its id, and without its sort orders; the ids it had, by number; and the
 * orders: key → the contents of its file (``readRank``). No key is left in the table with an empty list: a page opened
 * before the orders had files of their own would leave every record out of a sorted list.
 */
export function splitTable(bytes) {
  const { sortsAt } = readMeta(bytes);
  const orders = new Map();
  const sorts = new Reader(bytes, sortsAt);
  for (let left = sorts.list(); left > 0; left -= 1) {
    sorts.list();
    const key = sorts.text();
    orders.set(key, orderBytes(sorts.numbers()));
  }
  if (!orders.size) throw new Error("the table has no sort orders: were they taken out before?");
  const reader = new Reader(bytes);
  reader.list();
  reader.skipText();
  const total = reader.list();
  const parts = [bytes.subarray(0, reader.at)];
  const ids = [];
  for (let page = 0; page < total; page += 1) {
    reader.list();
    ids.push(reader.text());
    const wordsAt = reader.at;
    reader.number();
    const number = Buffer.from(String(page));
    // In CBOR: [number as a text, words].
    parts.push(Buffer.from([0x82, 0x60 | number.length]), number, bytes.subarray(wordsAt, reader.at));
  }
  parts.push(bytes.subarray(reader.at, sortsAt), EMPTY_LIST);
  return { table: Buffer.concat(parts), ids, orders };
}

/** Three bytes a page number, the highest of all pages first: in the order of a year these hardly change from page to
 * page, so that gzip makes 0.1 MB of 0.6. */
function orderBytes(pages) {
  const bytes = Buffer.alloc(pages.length * 3);
  pages.forEach((page, place) => {
    if (page > 0xffffff) throw new Error(`page ${page} in a sort order`);
    bytes[place] = page >> 16;
    bytes[pages.length + place] = page >> 8;
    bytes[2 * pages.length + place] = page;
  });
  return bytes;
}

/**
 * The records of ``ids`` from their fragments, in files of ``RECORDS_PER_FILE`` in the order of the index:
 * [{m: meta, w: index words}], gzip. Neighbours are alike (one volume, one section), so they compress well together.
 */
async function writeRecords(fragments, to, ids, words, hash) {
  const count = (await readdir(fragments)).filter((name) => name.endsWith(".pf_fragment")).length;
  if (count !== ids.length || words.size !== ids.length) throw new Error(`${words.size} entries, ${count} fragments, ${ids.length} records in the table`);
  await mkdir(to, { recursive: true });
  const sizes = [];
  for (let at = 0; at < ids.length; at += RECORDS_PER_FILE) {
    const records = await Promise.all(ids.slice(at, at + RECORDS_PER_FILE).map(async (id) => {
      const fragment = gunzipSync(await readFile(`${fragments}/${id}.pf_fragment`)).subarray(SIGNATURE.length);
      const { meta } = JSON.parse(fragment.toString("utf8"));
      if (!words.has(meta.id)) throw new Error(`no index words for ${meta.id} (${id})`);
      return { m: meta, w: words.get(meta.id) };
    }));
    const body = gzipSync(JSON.stringify(records), { level: 9 });
    hash.update(body);
    await writeFile(`${to}/${at / RECORDS_PER_FILE}.bin`, body);
    sizes.push(body.length);
  }
  return `records: ${ids.length} in ${sizes.length} files, ${Math.round(sizes.reduce((sum, size) => sum + size, 0) / 1e6)} MB`;
}

/** Pagefind 1.4 sometimes leaves pagefind-entry.json empty (1 of 240 made twelve at a time, 24 Nov 2026), and search then never starts. */
export async function ensureEntry(dir, pageCount) {
  const path = `${dir}/pagefind-entry.json`;
  if ((await readFile(path, "utf8").catch(() => "")).length > 20) return;
  const body = { version: "1.4.0", languages: { und: { hash: await tableName(dir), wasm: "unknown", page_count: pageCount } } };
  await writeFile(path, `${JSON.stringify(body, null, 2)}\n`);
  console.log("rewrote empty pagefind-entry.json");
}

async function tableName(dir) {
  const file = (await readdir(dir)).find((name) => /^pagefind\..+\.pf_meta$/.test(name));
  if (!file) throw new Error(`no pagefind.*.pf_meta in ${dir}`);
  return file.slice("pagefind.".length, -".pf_meta".length);
}

/**
 * Writes these files for the index in ``dir``, with the index words of each entry id (``words``). The browser keeps the
 * index's files by their names, and a number means another record in another index, so the table gets a new name, from
 * the contents of all of them, and the others are named after it. Gives what was done, for the log.
 */
export async function writeIndexFiles(dir, words) {
  const before = await tableName(dir);
  const stored = await readFile(`${dir}/pagefind.${before}.pf_meta`);
  const { table, ids, orders } = splitTable(gunzipSync(stored).subarray(SIGNATURE.length));
  await ensureEntry(dir, ids.length);
  const entry = await readFile(`${dir}/pagefind-entry.json`, "utf8");
  if (!entry.includes(before)) throw new Error(`pagefind-entry.json does not name ${before}`);
  const hash = createHash("sha256").update(table);
  for (const [key, order] of orders) hash.update(key).update(order);
  const records = await writeRecords(`${dir}/fragment`, `${dir}/records-new`, ids, words, hash);
  const name = `${before.slice(0, before.indexOf("_"))}_${hash.digest("hex").slice(0, 11)}`;
  await mkdir(`${dir}/records`, { recursive: true });
  await rename(`${dir}/records-new`, `${dir}/records/${name}`);
  await rm(`${dir}/fragment`, { recursive: true });
  await mkdir(`${dir}/sort`, { recursive: true });
  const sizes = [];
  for (const [key, order] of orders) {
    const body = gzipSync(order, { level: 9 });
    sizes.push(`${key} ${body.length}`);
    await writeFile(`${dir}/sort/${name}.${key}.bin`, body);
  }
  const small = gzipSync(Buffer.concat([SIGNATURE, table]), { level: 9 });
  await writeFile(`${dir}/pagefind.${name}.pf_meta`, small);
  await writeFile(`${dir}/pagefind-entry.json`, entry.replace(before, name));
  await rm(`${dir}/pagefind.${before}.pf_meta`);
  return `table: ${stored.length} → ${small.length} bytes, ${before} → ${name}; sort orders: ${sizes.join(", ")}; ${records}`;
}
