// Takes the sort orders out of Pagefind's table (pagefind.*.pf_meta), which every search reads first: they were 2.5 of
// its 4.1 MB (24 Nov 2026), and only a sorted list needs one of them. Each becomes a file of its own, sort/*.bin, that
// the site reads when it sorts a list (``loadRank`` in src/lib/searcher.ts); Pagefind is never asked to sort, and finds
// an index without sort orders.
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { gunzipSync, gzipSync } from "node:zlib";

import { Reader } from "../src/lib/cbor.ts";
import { readMeta } from "../src/lib/facets.ts";

const SIGNATURE = Buffer.from("pagefind_dcd");
/** In CBOR. */
const EMPTY_LIST = Buffer.from([0x80]);

/**
 * A table without its sort orders, and the orders: key → the contents of its file (``readRank``). No key is left in the
 * table with an empty list: a page opened before a deployment, which reads the orders there, would leave every record
 * out of a sorted list, where without the key it does not sort it.
 */
export function splitTable(bytes) {
  const { sortsAt } = readMeta(bytes);
  const reader = new Reader(bytes, sortsAt);
  const orders = new Map();
  for (let left = reader.list(); left > 0; left -= 1) {
    reader.list();
    const key = reader.text();
    orders.set(key, orderBytes(reader.numbers()));
  }
  if (!orders.size) throw new Error("the table has no sort orders: were they taken out before?");
  return { table: Buffer.concat([bytes.subarray(0, sortsAt), EMPTY_LIST]), orders };
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
 * Splits the table of the index in ``dir``. The browser keeps the index's files by their names, so the table gets a new
 * one, from its own contents and the orders', and the orders are named after it. Gives what was done, for the log.
 */
export async function writeSortFiles(dir) {
  const file = (await readdir(dir)).find((name) => /^pagefind\..+\.pf_meta$/.test(name));
  const before = file.slice("pagefind.".length, -".pf_meta".length);
  const stored = await readFile(`${dir}/${file}`);
  const { table, orders } = splitTable(gunzipSync(stored).subarray(SIGNATURE.length));
  const hash = createHash("sha256").update(table);
  for (const [key, order] of orders) hash.update(key).update(order);
  const name = `${before.slice(0, before.indexOf("_"))}_${hash.digest("hex").slice(0, 11)}`;
  const small = gzipSync(Buffer.concat([SIGNATURE, table]), { level: 9 });
  await mkdir(`${dir}/sort`, { recursive: true });
  const sizes = [];
  for (const [key, order] of orders) {
    const body = gzipSync(order, { level: 9 });
    sizes.push(`${key} ${body.length}`);
    await writeFile(`${dir}/sort/${name}.${key}.bin`, body);
  }
  await writeFile(`${dir}/pagefind.${name}.pf_meta`, small);
  await rm(`${dir}/${file}`);
  // Where Pagefind left its entry file empty, ``ensureEntry`` (build-index.mjs) writes it later, with the table's name.
  const entry = await readFile(`${dir}/pagefind-entry.json`, "utf8").catch(() => "");
  if (entry.includes(before)) await writeFile(`${dir}/pagefind-entry.json`, entry.replace(before, name));
  else if (entry.length > 20) throw new Error(`pagefind-entry.json does not name ${before}`);
  return `table: ${stored.length} → ${small.length} bytes, ${before} → ${name}; sort orders: ${sizes.join(", ")}`;
}
