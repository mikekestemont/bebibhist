import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdir, readFile, readdir, rename, rm, stat, writeFile } from "node:fs/promises";
import readline from "node:readline";
import { createIndex, close } from "pagefind";

const CROSS_REF =
  /\s*\[?\s*(?:cfr|voir|zie)\.?\s+n(?:°|º|o|r)\.?\s*(?:\d{2,6}(?:\s*(?:bis|ter|quater))?(?:\s*[,;]\s*|\s+(?:et|en|and)\s+)?)+\]?/gi;

const recordsPath = new URL("../../build/records.jsonl", import.meta.url);
const synonymsPath = new URL("../../data/curated/place_synonyms.csv", import.meta.url);
const schemePath = new URL("../../data/curated/scheme.csv", import.meta.url);
const outputPath = new URL("../public/pagefind", import.meta.url).pathname;
const stagingPath = new URL("../public/pagefind-build", import.meta.url).pathname;
const browsePath = new URL("../public/browse.json", import.meta.url).pathname;
// Counts for the subject tree, made here once: in the browser, Pagefind needs seconds to count a large group.
const browse = {};
const wordsPath = new URL("../public/words", import.meta.url).pathname;
// Every indexed word with its number of entries and its most common spelling, for "Did you mean …?".
const words = new Map();

/**
 * Wordings that only name one of the broad subject areas (or say "general"): the subject tags already say this, so
 * they are not shown as a finer subject. Everything else in a code's label or a printed heading is finer
 * information: a topic (Le protestantisme, Toponymie), a region (Brabant; Limbourg …) or a time (L'occupation).
 */
const BROAD_WORDINGS = new Set([
  "generalites", "algemeenheden", "travaux generaux", "algemene werken", "etudes generales", "par secteurs fonctionnels",
  "histoire par secteurs fonctionnels", "la vie politique", "la vie economique", "la vie economique et sociale",
  "la vie religieuse", "la vie culturelle", "la vie culturelle l enseignement les sciences les arts",
  "histoire sociale", "histoire culturelle", "histoire des institutions et histoire politique",
  "les institutions et la vie politique droit", "histoire de la vie religieuse et de la laicite",
].map(wording));

const synonyms = await loadSynonyms(synonymsPath);
const scheme = await loadScheme(schemePath);
const language = "und";
const { index, errors } = await createIndex({ forceLanguage: language });
if (!index) {
  console.error(errors.join("\n"));
  process.exit(1);
}

const containers = await countContainers(recordsPath);
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
  const container = containerOf(record, containers);
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
  countWords(content);
  const response = await index.addCustomRecord({
    url: `#/record/${encodeURIComponent(record.id)}`,
    content: `${record.id}\n${stripMarks(content).slice(0, 4000)}\n${fieldTokens(record)}${container ? ` hk_${container.hash}` : ""}`,
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
      ...specificMeta(record, scheme),
      authors: nameLine((record.persons || []).filter((person) => person.role !== "editor")).slice(0, 300),
      editors: nameLine((record.persons || []).filter((person) => person.role === "editor")).slice(0, 300),
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
      inVolume: volumeLine(record),
      extent: record.extent || "",
      seriesTitle: record.series?.title || "",
      seriesNumber: record.series?.number || "",
      kind: record.type || "",
      themes: (record.theme || []).join("|"),
      themesSuggested: (record.theme_suggested || []).join("|"),
      periods: (record.period || []).join("|"),
      periodsSuggested: (record.period_suggested || []).join("|"),
      similar: similarLine(record),
      container: container?.hash || "",
      containerCount: container ? String(container.count) : "",
    },
    filters: countBrowse(filters(record)),
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
await writeFile(browsePath, JSON.stringify(browse));
await writeWords(wordsPath, words);
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

/**
 * A collected volume and its chapters share one key: the volume's id when the chapter links to it,
 * otherwise the host title within the same BGB year. Journals are left out.
 */
function containerKey(record) {
  if (record.role !== "entry" || record.is_cross_listing) return null;
  if (record.type === "book") return record.id;
  if (record.type !== "chapter") return null;
  if (record.host?.id) return record.host.id;
  const title = fold(record.host?.title || "");
  return title ? `${record.bgb_year}|${title}` : null;
}

async function countContainers(path) {
  const counts = new Map();
  const lines = readline.createInterface({ input: createReadStream(path, { encoding: "utf8" }), crlfDelay: Infinity });
  for await (const line of lines) {
    if (!line.trim()) continue;
    const key = containerKey(JSON.parse(line));
    if (key) counts.set(key, (counts.get(key) || 0) + 1);
  }
  return counts;
}

/** Only a volume with at least two entries in it (itself and a chapter, or two chapters) gets a link. */
function containerOf(record, counts) {
  const key = containerKey(record);
  const count = key ? counts.get(key) || 0 : 0;
  if (count < 2) return null;
  return { hash: createHash("sha1").update(key).digest("hex").slice(0, 12), count };
}

/** Precomputed neighbours as "id score|id score", read by the similar-publications page. */
/** Subject area → period → decade of publication, with counts; the same values as the Pagefind filters. */
function countBrowse(values) {
  const year = Number(values.pubyear?.[0]);
  const decade = year ? String(Math.floor(year / 10) * 10) : "";
  for (const theme of values.theme || []) {
    const node = (browse[theme] ??= { n: 0, periods: {} });
    node.n += 1;
    for (const period of values.period || []) {
      const child = (node.periods[period] ??= { n: 0, decades: {} });
      child.n += 1;
      if (decade) child.decades[decade] = (child.decades[decade] || 0) + 1;
    }
  }
  return values;
}

function countWords(text) {
  const seen = new Set();
  for (const [surface] of stripMarks(text).matchAll(/[\p{L}][\p{L}'’]*[\p{L}]/gu)) {
    const key = surface.toLowerCase().replace(/['’]/g, "");
    if (key.length < 4 || seen.has(key)) continue;
    seen.add(key);
    const entry = words.get(key) || { n: 0, forms: new Map() };
    entry.n += 1;
    entry.forms.set(surface, (entry.forms.get(surface) || 0) + 1);
    words.set(key, entry);
  }
}

/**
 * Words in files by their first two letters ("va.json"), so the site fetches only the few kilobytes it needs, and
 * only after a search. A word in a single entry is left out: most are typing or OCR errors, the very words a
 * suggestion should not offer.
 */
async function writeWords(dir, all) {
  const shards = new Map();
  for (const [key, entry] of all) {
    if (entry.n < 2) continue;
    const form = [...entry.forms].sort((left, right) => right[1] - left[1])[0][0];
    const shard = /^[a-z]{2}/.test(key) ? key.slice(0, 2) : "_";
    if (!shards.has(shard)) shards.set(shard, {});
    shards.get(shard)[key] = form === key ? [entry.n] : [entry.n, form];
  }
  await rm(dir, { recursive: true, force: true });
  await mkdir(dir, { recursive: true });
  for (const [shard, entries] of shards) await writeFile(`${dir}/${shard}.json`, JSON.stringify(entries));
}

function similarLine(record) {
  const scores = record.similar_scores || [];
  return (record.similar || []).map((id, index) => `${id} ${scores[index] ?? ""}`.trim()).join("|");
}

/** A contribution split from its volume's printed contents names the volume, which is printed only at the head of that entry. */
function volumeLine(record) {
  if (!(record.provenance?.flags || []).includes("split-from-contents") || !record.host?.title) return "";
  const host = record.host;
  if (record.type === "article") {
    return `In: ${[host.title, host.volume, host.year, host.issue].filter(Boolean).join(", ")}`;
  }
  const editors = nameLine(host.editors);
  const imprint = [host.publisher?.place, host.publisher?.name, host.year].filter(Boolean).join(", ");
  return `In: ${editors ? `${editors} (eds.). ` : ""}${host.title}${imprint ? `. ${imprint}` : ""}`;
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

function wording(text) {
  return fold(text || "").replace(/[^a-z0-9]+/g, " ").trim();
}

/**
 * The finest subject an entry has, in each language: the last part of its BHB code's label, or else of the printed
 * heading it stands under. Empty when that only repeats a broad subject area.
 */
function specificMeta(record, labels) {
  const coded = (record.categories || []).filter((item) => item.code && labels[item.code]);
  const primary = coded.find((item) => item.primary) || coded.sort((left, right) => right.code.length - left.code.length)[0];
  if (primary) {
    const names = labelled(labels, primary.code);
    const parts = { fr: lastPart(names.fr), nl: lastPart(names.nl), en: lastPart(names.en) };
    if (parts.fr && !BROAD_WORDINGS.has(wording(parts.fr))) {
      return { specificFr: parts.fr, specificNl: parts.nl, specificEn: parts.en, specificFrom: primary.code, specificMachine: primary.machine ? "1" : "" };
    }
    // A code with a broad wording says nothing finer; one without any wording (II.B.) leaves the printed heading.
    if (parts.fr) return {};
  }
  const heading = (record.section_path || []).slice(-1)[0] || "";
  const [fr, nl] = halves(heading.replace(/^[\s(]*(?:[0-9]+|[a-zA-Z]|[IVXLC]+)[.)]\s*/, "").replace(/\s*\([¹²³⁴⁵⁶⁷⁸⁹⁰\d]+\)/g, "").trim());
  if (!fr || BROAD_WORDINGS.has(wording(fr)) || BROAD_WORDINGS.has(wording(nl))) return {};
  return { specificFr: fr, specificNl: nl || fr, specificEn: fr, specificFrom: "printed", specificMachine: "" };
}

function lastPart(label) {
  return (label || "").split(" / ").slice(-1)[0].trim();
}

/** A printed heading gives French and Dutch, joined by a dash: "Les arts — De kunsten". */
function halves(heading) {
  const split = heading.split(/\s+[—–-]\s+/);
  return split.length === 2 ? [split[0].trim().replace(/[.;,]$/, ""), split[1].trim().replace(/[.;,]$/, "")] : [heading.replace(/[.;,]$/, ""), ""];
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
