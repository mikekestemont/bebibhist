import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { gunzipSync } from "node:zlib";
import { mkdir, readFile, readdir, rename, rm, stat, writeFile } from "node:fs/promises";
import readline from "node:readline";
import { createIndex, close } from "pagefind";

import { keyWord } from "../src/lib/words.js";

const CROSS_REF =
  /\s*\[?\s*(?:cfr|voir|zie)\.?\s+n(?:°|º|o|r)\.?\s*(?:\d{2,6}(?:\s*(?:bis|ter|quater))?(?:\s*[,;]\s*|\s+(?:et|en|and)\s+)?)+\]?/gi;

const recordsPath = new URL("../../build/records.jsonl", import.meta.url);
const synonymsPath = new URL("../../data/curated/place_synonyms.csv", import.meta.url);
const schemePath = new URL("../../data/curated/scheme.csv", import.meta.url);
const outputPath = new URL("../public/pagefind", import.meta.url).pathname;
const stagingPath = new URL("../public/pagefind-build", import.meta.url).pathname;
const gazetteerPath = new URL("../../data/curated/gazetteer.csv", import.meta.url);
const journalsPath = new URL("../../data/curated/journals.csv", import.meta.url);
const topicRegionsPath = new URL("../../data/curated/topic_regions.json", import.meta.url);
const placesPath = new URL("../public/places.json", import.meta.url).pathname;
const aliasesPath = new URL("../../data/curated/scheme_aliases.csv", import.meta.url);
const subjectsPath = new URL("../public/subjects.json", import.meta.url).pathname;
// Entries per code of the Bibliography's classification, those of its sub-codes included, for the subject tree.
const subjectCounts = new Map();
// Entries per place, for the map and the place names on the site.
const placeCounts = new Map();
// Entries per place and period, for the map's choice of period: place → period → count.
const placePeriods = new Map();
const wordsPath = new URL("../public/words", import.meta.url).pathname;
const knownPath = new URL("../public/known", import.meta.url).pathname;
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
/** Begins the translated titles in a record's content; a sign, so it is no word of the index. */
const TRANSLATED = "⁂";
/** Joins the French and Dutch halves of a printed heading. */
const DASH = /\s+[—–-]\s+/;
const scheme = await loadScheme(schemePath);
const aliases = await loadAliases(aliasesPath);
const journals = await loadJournals(journalsPath);
const topicChains = await loadTopicChains(topicRegionsPath);
const language = "und";
const { index, errors } = await createIndex({ forceLanguage: language });
if (!index) {
  console.error(errors.join("\n"));
  process.exit(1);
}

const containers = await countContainers(recordsPath);
const merged = await mergedHeadings(recordsPath);
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
    // Words the citation pass read as OCR errors, corrected: for search only, never shown.
    (record.ocr_corrected || []).join(" "),
  ].filter(Boolean).join("\n"), synonyms);
  // Machine translations of the title (``bhb citations apply``), for search only: after the marker, so the page
  // can tell a hit found only through them, and never shown.
  // Only the words the record does not already have, each once: names, dates and places stay as printed in a
  // translation, and repeated they would rank a title about Kestemont above the titles by him.
  const translations = Object.values(record.translations || {}).filter(Boolean).join("\n");
  const translated = newWords(translations, content);
  const translatedTitle = newWords(translations, record.title || "");
  countWords(translated ? `${content}\n${translated}` : content);
  const own = stripMarks(content).slice(0, 4000);
  const response = await index.addCustomRecord({
    url: `#/record/${encodeURIComponent(record.id)}`,
    // The record's own words once more with a tag ("og_", "ot_" for the title), so a search can leave the
    // translations out and still count its hits exactly (the switch "also search machine translations").
    content: `${[record.id, ...(record.former_ids || [])].join(" ")}\n${own}\n${fieldTokens(record)}${container ? ` hk_${container.hash}` : ""}${regionWords(record)}${keyWords(record)}\n${prefixed("og", own)} ${prefixed("ot", record.title)}${
      translated ? `\n${TRANSLATED}\n${stripMarks(translated).slice(0, 2000)}\n${prefixed("ti", translatedTitle)}` : ""}`,
    language,
    meta: {
      id: record.id,
      // Ids the entry had in earlier releases (a repaired printed number), so old links still open it.
      formerIds: (record.former_ids || []).join("|"),
      title: (record.title || citation).slice(0, 180),
      citation: presentCitation(citation),
      year: record.bgb_year ? String(record.bgb_year) : "",
      number: record.print_number || "",
      section: (record.section_path || []).slice(-1)[0] || "",
      source: record.source || "",
      ...categoryMeta(record, scheme),
      ...specificMeta(record, scheme, merged),
      authors: nameLine((record.persons || []).filter((person) => person.role !== "editor")).slice(0, 300),
      editors: nameLine((record.persons || []).filter((person) => person.role === "editor")).slice(0, 300),
      // ORCID iDs (machine-derived), per name as the name line shows it: "Name (Given)\tiD\tsource|…".
      orcids: (record.persons || []).filter((person) => person.orcid)
        .map((person) => `${person.given ? `${person.family} (${person.given})` : person.family}\t${person.orcid}\t${person.orcid_from || ""}`).join("|"),
      // Given names written out from KBR (machine-derived), per name as the name line shows it:
      // "Name (Given)\tgiven name\tdates\tKBR authority id\tsource|…".
      fullNames: [...(record.persons || []), ...(record.host?.editors || [])].filter((person) => person.given_full || person.kbr_id)
        .map((person) => [person.given ? `${person.family} (${person.given})` : person.family, person.given_full || "", person.dates || "", person.kbr_id || "", person.name_from || ""].join("\t")).join("|"),
      kbr: record.kbr || "",
      // The fields were read from the printed text by the citation pass (``bhb citations apply``), not the rules.
      parsedLlm: (record.provenance?.flags || []).includes("parsed-llm") ? "1" : "",
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
      hostMatched: (record.provenance?.flags || []).includes("host-title-matched") ? "1" : "",
      hostFromIbid: (record.provenance?.flags || []).includes("host-from-ibid") ? "1" : "",
      journalId: record.journal_id || "",
      journalTitle: (record.journal_id && journals.get(record.journal_id)) || "",
      doi: record.doi || "",
      free: record.free_to_read ? record.identifiers_from?.free || "1" : "",
      isbn: (record.isbn || []).join("|"),
      issn: (record.issn || []).join("|"),
      identifiersFrom: Object.entries(record.identifiers_from || {}).map(([kind, source]) => `${kind}:${source}`).join("|"),
      imprintMachine: !record.publisher && (record.provenance?.flags || []).includes("host-from-cross-ref") ? "1" : "",
      inVolume: volumeLine(record),
      extent: record.extent || "",
      seriesTitle: record.series?.title || "",
      seriesNumber: record.series?.number || "",
      kind: record.type || "",
      places: (record.places || []).join("|"),
      placeIds: (record.place_ids || []).join("|"),
      placesSuggested: record.place_suggested?.length ? "1" : "",
      themes: (record.theme || []).join("|"),
      themesSuggested: (record.theme_suggested || []).join("|"),
      periods: (record.period || []).join("|"),
      periodsSuggested: (record.period_suggested || []).join("|"),
      // Languages a machine read in the title (``bhb language apply``), and how: "title", "bilingual", "journal" or
      // "volume" (a title of names only takes its journal's or volume's language).
      languages: (record.language_suggested || []).join("|"),
      languageFrom: languageRoute(record),
      similar: similarLine(record),
      container: container?.hash || "",
      containerCount: container ? String(container.count) : "",
    },
    // Places and journal narrow a search through words (keyWords), not filters: their counts are never shown.
    filters: withoutKeys(countBrowse(filters(record), record)),
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
await writeKnownWords(`${outputPath}/index`, knownPath);
await writeFile(subjectsPath, JSON.stringify(subjectsDocument(scheme, subjectCounts)));
await writePlaces(placesPath, placeCounts, placePeriods);
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
  if (record.place_ids?.length) values.place = record.place_ids;
  if (record.journal_id) values.journal = [record.journal_id];
  values.theme = record.theme?.length ? record.theme : ["unclassified"];
  if (record.language_suggested?.length) values.language = [...new Set(record.language_suggested.map(languageFacet))];
  // Free to read (OpenAlex or Persée, through the DOI): a filter of one value.
  if (record.free_to_read) values.access = ["free"];
  const when = chronology(record);
  if (when.pubyear) values.pubyear = [when.pubyear];
  return values;
}

/** The languages with a value of their own in the filter: the four that cover 99 % of the entries (2 Nov 2026). The
 * rarer ones (Spanish, Italian, Latin, each under 0.3 %) are grouped under "other"; the entry still names its language. */
function languageFacet(code) {
  return ["nl", "fr", "en", "de"].includes(code) ? code : "other";
}

function languageRoute(record) {
  const flags = record.provenance?.flags || [];
  if (!record.language_suggested?.length) return "";
  if (flags.includes("language-bilingual")) return "bilingual";
  if (flags.includes("language-from-journal")) return "journal";
  if (flags.includes("language-from-volume")) return "volume";
  return "title";
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
  const authors = (record.persons || []).map((person) => [person.family, person.given, person.given_full].filter(Boolean).join(" ")).join(" ");
  return [prefixed("ti", record.title), prefixed("au", authors), prefixed("in", record.host?.title), prefixed("se", record.series?.title)].filter(Boolean).join(" ");
}

/** The folded words of ``text`` that ``own`` lacks, each once, joined by spaces. */
function newWords(text, own) {
  const seen = new Set(fold(own).match(/[\p{L}\p{N}]+/gu) || []);
  const words = fold(text).match(/[\p{L}\p{N}]+/gu) || [];
  return words.filter((word) => !seen.has(word) && seen.add(word)).join(" ");
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
    .map((person) => [person.family, person.given, person.given_full].filter(Boolean).join(" "))
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
/** The words that let a search be narrowed to the entry's places or its journal (src/lib/words.js). */
function keyWords(record) {
  const words = (record.place_ids || []).map((place) => keyWord("pl", place));
  if (record.journal_id) words.push(keyWord("jn", record.journal_id));
  // The entry's code of the classification and every code above it, so a subject of the tree opens with all the
  // entries of its sub-subjects (#/search?subject=III.D.2.b.).
  for (const code of codeChain(record)) words.push(keyWord("sc", code));
  return words.map((word) => ` ${word}`).join("");
}

function withoutKeys(values) {
  const { place, journal, ...kept } = values;
  return kept;
}

/** The words that mark the entry's regions on the map of subjects, at every level, so a region opens as a search
 * (#/search?topic=…). Words, not a filter: Pagefind counts every filter value on every search, and 744 more values
 * made all searches slower (7 Nov 2026). The same format as ``regionWord`` in src/lib/topics.ts. */
function regionWords(record) {
  const chain = topicChains.get(record.topic) || [];
  return chain.map((id) => {
    const [level, number] = id.replace(/^r/, "").split(".");
    return ` rg_${level}${number.padStart(3, "0")}`;
  }).join("");
}

/** Finest region of the map of subjects → its region at every level, coarsest first (`bhb topicmap names`). */
async function loadTopicChains(path) {
  let regions;
  try {
    regions = JSON.parse(await readFile(path, "utf8")).regions;
  } catch {
    return new Map();
  }
  const byId = new Map(regions.map((region) => [region.id, region]));
  const out = new Map();
  for (const region of regions) {
    const chain = [];
    for (let at = region; at; at = at.parent ? byId.get(at.parent) : null) chain.unshift(at.id);
    out.set(region.id, chain);
  }
  return out;
}

/** Journal id → its full title, from the machine-built journal list (`bhb journals apply`). */
async function loadJournals(path) {
  const rows = parseCsv(await readFile(path, "utf8"));
  const column = Object.fromEntries(rows[0].map((name, index) => [name, index]));
  return new Map(rows.slice(1).map((row) => [row[column.id], row[column.title]]));
}

/** Every place the entries mention, with its names, its level and coordinates from the gazetteer, its count, and
 * its count per period (``p``, only the periods with entries). */
async function writePlaces(path, counts, periods) {
  const rows = parseCsv(await readFile(gazetteerPath, "utf8"));
  const column = Object.fromEntries(rows[0].map((name, index) => [name, index]));
  const gazetteer = new Map(rows.slice(1).map((row) => [`nis:${row[column.nis]}`, row]));
  const places = {};
  for (const [key, n] of counts) {
    const row = gazetteer.get(key);
    if (row) {
      places[key] = {
        fr: row[column.label_fr], nl: row[column.label_nl], de: row[column.label_de], en: row[column.label_en],
        level: row[column.level], lon: Number(row[column.lon]) || null, lat: Number(row[column.lat]) || null, n,
        p: periods.get(key) || {},
      };
    } else {
      const name = key.replace(/^name:/, "");
      places[key] = { fr: name, nl: name, de: name, en: name, level: "printed", lon: null, lat: null, n, p: periods.get(key) || {} };
    }
  }
  await writeFile(path, JSON.stringify(places));
}

function countBrowse(values, record) {
  for (const code of codeChain(record)) subjectCounts.set(code, (subjectCounts.get(code) || 0) + 1);
  for (const place of values.place || []) {
    placeCounts.set(place, (placeCounts.get(place) || 0) + 1);
    const byPeriod = placePeriods.get(place) || {};
    for (const period of values.period || []) byPeriod[period] = (byPeriod[period] || 0) + 1;
    placePeriods.set(place, byPeriod);
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
      source: row[column.source] || "",
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
function specificMeta(record, labels, merged = new Map()) {
  const coded = (record.categories || []).filter((item) => item.code && labels[item.code]);
  const primary = coded.find((item) => item.primary) || coded.sort((left, right) => right.code.length - left.code.length)[0];
  if (primary) {
    const names = labelled(labels, primary.code);
    const parts = { fr: lastPart(names.fr), nl: lastPart(names.nl), en: lastPart(names.en) };
    if (parts.fr && !BROAD_WORDINGS.has(wording(parts.fr))) {
      return { specificFr: parts.fr, specificNl: parts.nl, specificEn: parts.en, specificFrom: currentCode(primary.code), specificMachine: primary.machine ? "1" : "" };
    }
    // A code with a broad wording says nothing finer; one without any wording (II.B.) leaves the printed heading.
    if (parts.fr) return {};
  }
  const printed = (record.section_path || []).slice(-1)[0] || "";
  const heading = merged.get(printed) || printed;
  const [fr, nl] = halves(heading.replace(/^[\s(]*(?:[0-9]+|[a-zA-Z]|[IVXLC]+)[.)]\s*/, "").replace(/\s*\([¹²³⁴⁵⁶⁷⁸⁹⁰\d]+\)/g, "").trim());
  if (!fr || BROAD_WORDINGS.has(wording(fr)) || BROAD_WORDINGS.has(wording(nl))) return {};
  return { specificFr: fr, specificNl: nl || fr, specificEn: fr, specificFrom: "printed", specificMachine: "" };
}

/** The entry's code of the classification (as its finer subject shows it) and the codes above it, finest first. */
function codeChain(record) {
  const coded = (record.categories || []).filter((item) => item.code && scheme[item.code]);
  const primary = coded.find((item) => item.primary) || [...coded].sort((left, right) => right.code.length - left.code.length)[0];
  const chain = [];
  for (let code = primary ? currentCode(primary.code) : ""; code && scheme[code] && !chain.includes(code); code = scheme[code].parent) chain.push(code);
  return chain;
}

/** Codes that some printed volumes of 1993–2008 numbered otherwise, to the code of the current classification
 * (data/curated/scheme_aliases.csv): the tree and a subject's search use the current one. */
async function loadAliases(path) {
  const rows = parseCsv(await readFile(path, "utf8"));
  const column = Object.fromEntries((rows[0] || []).map((name, index) => [name, index]));
  return new Map(rows.slice(1).filter((row) => row[column.code] && row[column.current_code]).map((row) => [row[column.code], row[column.current_code]]));
}

function currentCode(code) {
  return aliases.get(code) || code;
}

/**
 * The subject tree: every code of the current classification (the State Archives' scheme, as the volumes from 1993
 * on and the State Archives' records use it) with entries, in its order: code → [parent, entries with those of its
 * sub-codes, name in nl, fr, en]. A level without a wording of its own ("III.B.2.b.") takes its name from the labels
 * of the codes below it, whose paths name every level above ("… / De verschillende vorstendommen / Vlaanderen / …").
 */
function subjectsDocument(labels, counts) {
  const names = {};
  for (const [code, row] of Object.entries(labels)) {
    const depth = code.replace(/\.$/, "").split(".").length;
    for (const language of ["nl", "fr", "en"]) {
      const segments = (row[language] || "").split(" / ").map((part) => part.trim());
      if (segments.length !== depth || !segments[depth - 1]) continue;
      // The code's own name, and the names of the levels above it.
      let level = code;
      for (let index = depth - 1; index >= 0 && level; index -= 1) {
        const entry = (names[level] ??= {});
        if (!entry[language] || level === code) entry[language] = level === code ? segments[index] : entry[language] || segments[index];
        level = labels[level]?.parent || "";
      }
    }
  }
  const out = {};
  for (const [code, row] of Object.entries(labels)) {
    const n = counts.get(code) || 0;
    if (!n || row.source !== "vsmart") continue;
    const name = names[code] || {};
    const nl = name.nl || name.fr || "";
    const fr = name.fr || nl;
    out[code] = [row.parent, n, nl, fr, name.en || fr];
  }
  return out;
}

function lastPart(label) {
  return (label || "").split(" / ").slice(-1)[0].trim();
}

/**
 * A printed heading gives French and Dutch, joined by a dash: "Les arts — De kunsten". Some (1993) pair them part
 * by part: "Les élections - verkiezingen; les partis - de partijen".
 */
function halves(heading) {
  const tidy = (text) => text.trim().replace(/[.;,]$/, "");
  const split = heading.split(DASH);
  if (split.length === 2) return [tidy(split[0]), tidy(split[1])];
  const pairs = heading.split(/;\s*/).map((part) => part.split(DASH));
  if (pairs.length > 1 && pairs.every((pair) => pair.length === 2)) {
    return [tidy(pairs.map((pair) => pair[0]).join("; ")), tidy(pairs.map((pair) => pair[1]).join("; "))];
  }
  return [tidy(heading), ""];
}

/**
 * Headings of two levels printed as one ("b. Flandre - Vlaanderen La dynastie; … - De dynastie; …", mostly the
 * first subheading of a section in BGB 2008), mapped to the finer level: what follows the longest heading that is
 * printed on its own elsewhere (another year, another level), or else an end that is, when it begins with a capital.
 */
async function mergedHeadings(path) {
  const bare = (heading) => heading.replace(/^[\s(]*(?:[0-9]+|[a-zA-Z]|[IVXLC]+)[.)]\s*/, "").replace(/\s+/g, " ").trim();
  const known = new Set();
  const long = new Set();
  const lines = readline.createInterface({ input: createReadStream(path, { encoding: "utf8" }), crlfDelay: Infinity });
  for await (const line of lines) {
    if (!line.trim()) continue;
    for (const heading of JSON.parse(line).section_path || []) {
      const parts = heading.split(DASH).length;
      if (parts === 2) known.add(bare(heading).replace(/[.;,]$/, ""));
      else if (parts > 2) long.add(heading);
    }
  }
  const found = new Map();
  for (const heading of long) {
    const text = bare(heading);
    let best = "";
    for (let at = text.indexOf(" "); at > 0; at = text.indexOf(" ", at + 1)) {
      const head = text.slice(0, at).replace(/[.;,]$/, "");
      const tail = text.slice(at + 1);
      if (/^\p{Lu}/u.test(tail) && (known.has(head) || (!best && known.has(tail.replace(/[.;,]$/, ""))))) best = tail;
    }
    if (best) found.set(heading, best);
  }
  return found;
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

/**
 * Every word in Pagefind's index, read from its own chunks, so the site can tell a word that is not in the index
 * from one that is: Pagefind 1.4, once the prefix chunks are loaded, answers an unknown word with every word that
 * shares its prefix (16,638 hits for "vanthemse"). Files by the word's first three letters ("van.txt"), or a field
 * word's tag and two letters ("au_va.txt"), one word a line, sorted. Ids and words with digits are left out: the
 * site only checks words of letters.
 */
async function writeKnownWords(indexDir, dir) {
  const shards = new Map();
  for (const file of await readdir(indexDir)) {
    const raw = gunzipSync(await readFile(`${indexDir}/${file}`)).subarray("pagefind_dcd".length);
    for (const word of chunkWords(raw)) {
      if (!/^(?:[a-z]{2}_)?\p{L}+$/u.test(word)) continue;
      const key = /^[a-z]{2}_/.test(word) ? word.slice(0, 5) : word.slice(0, 3);
      if (!shards.has(key)) shards.set(key, []);
      shards.get(key).push(word);
    }
  }
  await rm(dir, { recursive: true, force: true });
  await mkdir(dir, { recursive: true });
  for (const [key, list] of shards) await writeFile(`${dir}/${key}.txt`, list.sort().join("\n"));
  console.log(`known words: ${[...shards.values()].reduce((n, list) => n + list.length, 0)} in ${shards.size} files → ${dir}`);
}

/** The words of one Pagefind 1.4 index chunk, a CBOR array [[[word, pages], …]]; only what that needs is read. */
function chunkWords(buffer) {
  let at = 0;
  const head = () => {
    const byte = buffer[at++];
    const major = byte >> 5;
    const info = byte & 31;
    let value = info;
    if (info === 24) value = buffer[at++];
    else if (info === 25) { value = buffer.readUInt16BE(at); at += 2; }
    else if (info === 26) { value = buffer.readUInt32BE(at); at += 4; }
    else if (info === 27) { value = Number(buffer.readBigUInt64BE(at)); at += 8; }
    else if (info > 27) throw new Error(`unexpected CBOR byte ${byte} at ${at - 1}`);
    return [major, value];
  };
  const item = () => {
    const [major, value] = head();
    if (major === 0 || major === 1) return value;
    if (major === 2 || major === 3) {
      const text = buffer.toString(major === 3 ? "utf8" : "latin1", at, at + value);
      at += value;
      return text;
    }
    if (major === 4) return Array.from({ length: value }, item);
    if (major === 5) { for (let i = 0; i < value; i += 1) { item(); item(); } return null; }
    if (major === 6) return item();
    throw new Error(`unexpected CBOR major type ${major}`);
  };
  return item()[0].map((entry) => entry[0]);
}
