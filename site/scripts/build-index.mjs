import { createReadStream } from "node:fs";
import { readFile, readdir, rename, rm, stat, writeFile } from "node:fs/promises";
import readline from "node:readline";
import { createIndex, close } from "pagefind";

const CROSS_REF =
  /\s*\[?\s*(?:cfr|voir|zie)\.?\s+n(?:°|º|o|r)\.?\s*(?:\d{2,6}(?:\s*(?:bis|ter|quater))?(?:\s*[,;]\s*|\s+(?:et|en|and)\s+)?)+\]?/gi;

const recordsPath = new URL("../../build/records.jsonl", import.meta.url);
const synonymsPath = new URL("../../data/curated/place_synonyms.csv", import.meta.url);
const schemePath = new URL("../../data/curated/scheme.csv", import.meta.url);
const outputPath = new URL("../public/pagefind", import.meta.url).pathname;
const stagingPath = new URL("../public/pagefind-build", import.meta.url).pathname;

const synonyms = await loadSynonyms(synonymsPath);
const scheme = await loadScheme(schemePath);
const language = "und";
const { index, errors } = await createIndex({ forceLanguage: language });
if (!index) {
  console.error(errors.join("\n"));
  process.exit(1);
}

let indexed = 0;
let skipped = 0;
const input = createReadStream(recordsPath, { encoding: "utf8" });
const lines = readline.createInterface({ input, crlfDelay: Infinity });
for await (const line of lines) {
  if (!line.trim()) continue;
  const record = JSON.parse(line);
  if (record.role !== "entry" || record.is_cross_listing) {
    skipped += 1;
    continue;
  }
  const citation = record.printed || compose(record);
  const when = chronology(record);
  const content = expand([
    citation,
    record.title,
    record.subtitle,
    record.title_translated,
    people(record),
    record.host?.title,
    record.host?.subtitle,
    nameLine(record.host?.editors),
    (record.section_path || []).join(" "),
    record.note,
  ].filter(Boolean).join("\n"), synonyms);
  const response = await index.addCustomRecord({
    url: `#/record/${encodeURIComponent(record.id)}`,
    content: `${record.id}\n${stripMarks(content).slice(0, 4000)}\n${fieldTokens(record)}`,
    language,
    meta: {
      id: record.id,
      title: (record.title || citation).slice(0, 180),
      citation: presentCitation(citation),
      year: record.bgb_year ? String(record.bgb_year) : "",
      number: record.print_number || "",
      section: (record.section_path || []).slice(-1)[0] || "",
      source: record.source || "",
      ...categoryMeta(record, scheme),
      authors: peopleLine(record).slice(0, 300),
      subtitle: (record.subtitle || "").slice(0, 300),
      host: (record.host?.title || "").slice(0, 300),
      hostSubtitle: (record.host?.subtitle || "").slice(0, 300),
      hostEditors: nameLine(record.host?.editors).slice(0, 300),
      volume: record.host?.volume || "",
      issue: record.host?.issue || "",
      pages: record.host?.pages || "",
      pubyear: record.year ? String(record.year) : record.host?.year || "",
      yearFromVolume: when.fromVolume ? "1" : "",
      yearMachine: (record.provenance?.flags || []).includes("year-from-host") ? "1" : "",
      place: record.publisher?.place || record.host?.publisher?.place || "",
      publisher: record.publisher?.name || record.host?.publisher?.name || "",
      imprintMachine: !record.publisher && (record.provenance?.flags || []).includes("host-from-cross-ref") ? "1" : "",
      extent: record.extent || "",
      kind: record.type || "",
      similar: similarLine(record),
    },
    filters: filters(record),
    sort: sortKeys(record),
  });
  if (response.errors?.length) {
    console.error(record.id, response.errors.join("; "));
  }
  indexed += 1;
  if (indexed % 10000 === 0) console.log(`  ${indexed}`);
}

const previousPath = `${outputPath}-previous`;
await rm(stagingPath, { recursive: true, force: true });
const written = await index.writeFiles({ outputPath: stagingPath });
if (written.errors?.length) console.error(written.errors.join("\n"));
await close();
await rm(previousPath, { recursive: true, force: true });
try {
  await rename(outputPath, previousPath);
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
await rename(stagingPath, outputPath);
await rm(previousPath, { recursive: true, force: true });
const wasm = await stat(`${outputPath}/wasm.unknown.pagefind`);
if (wasm.size < 1000) {
  console.error(`pagefind wasm is ${wasm.size} bytes; search cannot start`);
  process.exit(1);
}
await ensureEntry(outputPath, indexed);
console.log(`indexed ${indexed} entries, skipped ${skipped} non-entries → ${outputPath}`);

/** Pagefind 1.4 sometimes leaves pagefind-entry.json empty, and search then never starts. */
async function ensureEntry(dir, pageCount) {
  const entryPath = `${dir}/pagefind-entry.json`;
  const entry = await stat(entryPath).catch(() => null);
  if (entry && entry.size > 20) return;
  const names = await readdir(dir);
  const meta = names.find((name) => name.startsWith("pagefind.") && name.endsWith(".pf_meta"));
  const hash = meta?.slice("pagefind.".length, -".pf_meta".length);
  if (!hash) {
    console.error("pagefind-entry.json is empty and no metadata file was found");
    process.exit(1);
  }
  const body = {
    version: "1.4.0",
    languages: { und: { hash, wasm: "unknown", page_count: pageCount } },
  };
  await writeFile(entryPath, `${JSON.stringify(body, null, 2)}\n`);
  console.log("rewrote empty pagefind-entry.json");
}

function sortKeys(record) {
  const published = String(record.year || record.host?.year || "").match(/\d{4}/);
  const first = (record.persons || [])[0];
  const author = first ? fold(`${first.family} ${first.given || ""}`) : "";
  return {
    year: record.bgb_year ? String(record.bgb_year) : "0000",
    pubyear: published ? published[0] : "0000",
    author: (author || "~").slice(0, 80),
    title: (fold(record.title || "") || "~").slice(0, 120),
  };
}

function filters(record) {
  const values = {
    type: [record.type || "other"],
  };
  if (record.period?.length) values.period = record.period;
  values.theme = record.theme?.length ? record.theme : ["unclassified"];
  const when = chronology(record);
  if (when.pubyear) values.pubyear = [when.pubyear];
  return values;
}

/** Publication year, or the volume year when that year is missing or outside 1945–today. */
function chronology(record) {
  const published = yearOf(record.year) || yearOf(record.host?.year);
  const volume = yearOf(record.bgb_year);
  const today = new Date().getFullYear();
  if (published >= 1945 && published <= today) return { pubyear: String(published), fromVolume: false };
  if (volume) return { pubyear: String(volume), fromVolume: true };
  return { pubyear: "", fromVolume: false };
}

function yearOf(value) {
  const match = String(value ?? "").match(/\d{4}/);
  return match ? Number(match[0]) : 0;
}

function fieldTokens(record) {
  const authors = (record.persons || []).map((person) => [person.family, person.given].filter(Boolean).join(" ")).join(" ");
  return [prefixed("ti", record.title), prefixed("au", authors), prefixed("in", record.host?.title)].filter(Boolean).join(" ");
}

function prefixed(tag, text) {
  const seen = new Set();
  const words = fold(String(text || "")).match(/[\p{L}\p{N}]+/gu) || [];
  return words
    .filter((word) => word.length > 1 && !seen.has(word) && seen.add(word))
    .map((word) => `${tag}_${word}`)
    .join(" ");
}

function people(record) {
  return (record.persons || [])
    .map((person) => [person.family, person.given].filter(Boolean).join(" "))
    .join(" ");
}

function peopleLine(record) {
  return nameLine(record.persons);
}

/** Precomputed neighbours as "id score|id score", read by the similar-publications page. */
function similarLine(record) {
  const scores = record.similar_scores || [];
  return (record.similar || []).map((id, index) => `${id} ${scores[index] ?? ""}`.trim()).join("|");
}

function nameLine(persons) {
  const names = (persons || []).map((person) =>
    person.given ? `${person.family} (${person.given})` : person.family,
  );
  if (names.length > 1) return `${names.slice(0, -1).join(", ")} & ${names.at(-1)}`;
  return names[0] || "";
}

function presentCitation(text) {
  return text
    .replaceAll("In :", "In:")
    .replace(CROSS_REF, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([.,])/g, "$1")
    .replace(/\.{2,}(?=\s*$)/g, ".")
    .replace(/(?<!\.)\.\.(?=[\s),;:]|$)/g, ".")
    .trim();
}

function compose(record) {
  return [people(record), record.title, record.host?.title].filter(Boolean).join(". ");
}

function expand(text, groups) {
  const extra = new Set();
  for (const token of text.matchAll(/[\p{L}\p{M}]+/gu)) {
    const group = groups.get(fold(token[0]));
    if (!group) continue;
    for (const form of group) extra.add(form);
  }
  return extra.size ? `${text}\n${[...extra].join(" ")}` : text;
}

async function loadSynonyms(path) {
  const groups = new Map();
  const text = await readFile(path, "utf8");
  for (const line of text.split(/\n/).slice(1)) {
    if (!line.trim()) continue;
    const [preferred, aliases = ""] = line.split(",");
    const forms = [preferred, ...aliases.split("|")].map((item) => item.trim()).filter(Boolean);
    for (const form of forms) groups.set(fold(form), forms);
  }
  return groups;
}

function stripMarks(text) {
  return text.normalize("NFD").replace(/\p{M}/gu, "");
}

function fold(text) {
  return stripMarks(text).toLowerCase();
}

async function loadScheme(path) {
  const rows = parseCsv(await readFile(path, "utf8"));
  const header = rows[0] || [];
  const column = Object.fromEntries(header.map((name, index) => [name, index]));
  const scheme = {};
  for (const row of rows.slice(1)) {
    const code = row[column.code];
    if (!code) continue;
    scheme[code] = {
      parent: row[column.parent] || "",
      fr: row[column.label_fr] || "",
      nl: row[column.label_nl] || "",
      en: row[column.label_en] || "",
    };
  }
  return scheme;
}

/** A parent such as II.B. has a code and no wording. Use the nearest labelled ancestor. */
function labelled(labels, code) {
  let current = code;
  const seen = new Set();
  while (current && labels[current] && !seen.has(current)) {
    seen.add(current);
    const row = labels[current];
    if (row.fr || row.nl || row.en) return row;
    current = row.parent;
  }
  return { fr: "", nl: "", en: "" };
}

function categoryMeta(record, labels) {
  const categories = record.categories || [];
  const coded = categories.filter((item) => item.code && labels[item.code]);
  const primary = coded.find((item) => item.primary) || coded.sort((left, right) => right.code.length - left.code.length)[0];
  if (primary) {
    const names = labelled(labels, primary.code);
    const hasLabel = names.fr || names.nl || names.en;
    return {
      categoryFr: names.fr,
      categoryNl: names.nl,
      categoryEn: names.en,
      categoryTheme: hasLabel ? "" : (record.theme || [])[0] || "",
      categoryDraft: names.en ? "1" : "",
      categoryMachine: primary.machine ? "1" : "",
      categorySource: primary.source || "",
    };
  }
  const themed = categories.find((item) => item.primary) || categories[0];
  return {
    categoryFr: "",
    categoryNl: "",
    categoryEn: "",
    categoryTheme: themed?.theme || (record.theme || [])[0] || "",
    categoryDraft: "",
    categoryMachine: themed?.machine ? "1" : "",
    categorySource: themed?.source || "",
  };
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else quoted = false;
      } else cell += char;
    } else if (char === '"') quoted = true;
    else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") cell += char;
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}
