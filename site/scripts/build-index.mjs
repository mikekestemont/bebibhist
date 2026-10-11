import { createReadStream } from "node:fs";
import { readFile, rename, rm, stat } from "node:fs/promises";
import readline from "node:readline";
import { createIndex, close } from "pagefind";

const recordsPath = new URL("../../build/records.jsonl", import.meta.url);
const synonymsPath = new URL("../../data/curated/place_synonyms.csv", import.meta.url);
const outputPath = new URL("../public/pagefind", import.meta.url).pathname;
const stagingPath = new URL("../public/pagefind-build", import.meta.url).pathname;

const synonyms = await loadSynonyms(synonymsPath);
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
    content: `${record.id}\n${stripMarks(content)}`.slice(0, 4000),
    language,
    meta: {
      id: record.id,
      title: (record.title || citation).slice(0, 180),
      citation: presentCitation(citation),
      year: record.bgb_year ? String(record.bgb_year) : "",
      number: record.print_number || "",
      section: (record.section_path || []).slice(-1)[0] || "",
      authors: peopleLine(record).slice(0, 300),
      subtitle: (record.subtitle || "").slice(0, 300),
      host: (record.host?.title || "").slice(0, 300),
      hostSubtitle: (record.host?.subtitle || "").slice(0, 300),
      hostEditors: nameLine(record.host?.editors).slice(0, 300),
      volume: record.host?.volume || "",
      issue: record.host?.issue || "",
      pages: record.host?.pages || "",
      pubyear: record.year ? String(record.year) : record.host?.year || "",
      place: record.publisher?.place || "",
      publisher: record.publisher?.name || "",
      extent: record.extent || "",
      kind: record.type || "",
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
console.log(`indexed ${indexed} entries, skipped ${skipped} non-entries → ${outputPath}`);

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
    source: [record.source || "unknown"],
  };
  if (record.period?.length) values.period = record.period;
  if (record.bgb_year) {
    values.year = [String(record.bgb_year)];
    values.decade = [String(Math.floor(record.bgb_year / 10) * 10)];
  }
  return values;
}

function people(record) {
  return (record.persons || [])
    .map((person) => [person.family, person.given].filter(Boolean).join(" "))
    .join(" ");
}

function peopleLine(record) {
  return nameLine(record.persons);
}

function nameLine(persons) {
  const names = (persons || []).map((person) =>
    person.given ? `${person.family} (${person.given})` : person.family,
  );
  if (names.length > 1) return `${names.slice(0, -1).join(", ")} & ${names.at(-1)}`;
  return names[0] || "";
}

const CROSS_REF =
  /\s*\[?\s*(?:cfr|voir|zie)\.?\s+n(?:°|º|o|r)\.?\s*(?:\d{2,6}(?:\s*(?:bis|ter|quater))?(?:\s*[,;]\s*|\s+(?:et|en|and)\s+)?)+\]?/gi;

function presentCitation(text) {
  return text
    .replaceAll("In :", "In:")
    .replace(CROSS_REF, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([.,])/g, "$1")
    .replace(/\.{2,}(?=\s*$)/g, ".")
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
