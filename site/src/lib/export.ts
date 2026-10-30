import { presentCitation, type Hit } from "./search";

export type ExportKind = "txt" | "bibtex" | "ris" | "mods";

/** A result list is saved up to this many hits, in the order on screen. */
export const EXPORT_CAP = 500;

interface Name {
  family: string;
  given: string;
}

const DATA_RIGHTS = "CC BY-NC 4.0. https://creativecommons.org/licenses/by-nc/4.0/";

const BIB = {
  article: "article",
  chapter: "incollection",
  book: "book",
  "journal-issue": "misc",
  other: "misc",
} as const;

const RIS = {
  article: "JOUR",
  chapter: "CHAP",
  book: "BOOK",
  "journal-issue": "JFULL",
  other: "GEN",
} as const;

export function exportRecord(
  hit: Hit,
  kind: ExportKind,
  source: string,
  sourceLabel = "Source",
): { filename: string; mime: string; body: string } {
  const stem = (hit.meta.id || "bhb").replace(/[^A-Za-z0-9._-]+/g, "-");
  const ext = { txt: "txt", bibtex: "bib", ris: "ris", mods: "xml" }[kind];
  const mime = kind === "mods" ? "application/xml" : "text/plain";
  return { filename: `${stem}.${ext}`, mime: `${mime};charset=utf-8`, body: writers[kind](hit, source, sourceLabel) };
}

export function saveExport(hit: Hit, kind: ExportKind, source: string, sourceLabel = "Source"): void {
  download(exportRecord(hit, kind, source, sourceLabel));
}

export function saveExports(
  hits: Hit[],
  kind: ExportKind,
  source: string,
  sourceLabel: string,
  stem: string,
  total: number,
): void {
  const ext = { txt: "txt", bibtex: "bib", ris: "ris", mods: "xml" }[kind];
  const mime = kind === "mods" ? "application/xml" : "text/plain";
  download({
    filename: `${stem}.${ext}`,
    mime: `${mime};charset=utf-8`,
    body: bundle(hits, kind, source, sourceLabel, total),
  });
}

function download(file: { filename: string; mime: string; body: string }): void {
  const blob = new Blob([file.body], { type: file.mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.filename;
  link.click();
  URL.revokeObjectURL(url);
}

function bundle(hits: Hit[], kind: ExportKind, source: string, sourceLabel: string, total: number): string {
  const capped = total > hits.length ? `${hits.length} / ${total}` : "";
  if (kind === "txt") {
    const citations = hits.map((hit) => presentCitation(hit.meta.citation || hit.meta.title || "")).join("\n\n");
    return `${capped ? `${capped}\n\n` : ""}${citations}\n\n${sourceLabel}: ${source}\n${DATA_RIGHTS}\n`;
  }
  if (kind === "mods") {
    const entries = hits.map((hit) => mods(hit, source).replace(/^<\?xml[^>]*>\n/, "")).join("\n");
    const note = capped ? `<!-- ${capped} -->\n` : "";
    return `<?xml version="1.0" encoding="utf-8"?>\n<modsCollection xmlns="http://www.loc.gov/mods/v3">\n${note}${entries}</modsCollection>\n`;
  }
  const joined = hits.map((hit) => writers[kind](hit, source, sourceLabel)).join(kind === "bibtex" ? "\n" : "");
  if (kind === "bibtex") return `% ${DATA_RIGHTS}\n${capped ? `% ${capped}\n` : ""}\n${joined}`;
  return joined;
}

const writers: Record<ExportKind, (hit: Hit, source: string, sourceLabel: string) => string> = {
  txt: (hit, source, sourceLabel) =>
    `${presentCitation(hit.meta.citation || hit.meta.title || "")}\n\n${sourceLabel}: ${source}\n${DATA_RIGHTS}\n`,
  bibtex: (hit, source) => bibtex(hit, source),
  ris: (hit, source) => ris(hit, source),
  mods: (hit, source) => mods(hit, source),
};

function bibtex(hit: Hit, source: string): string {
  const meta = hit.meta;
  const kind = kindOf(meta.kind);
  const authors = people(meta.authors);
  const editors = people(meta.hostEditors);
  const fields: [string, string][] = [
    ["author", authors.map(bibName).join(" and ")],
    ["editor", kind === "chapter" ? editors.map(bibName).join(" and ") : ""],
    ["title", [meta.title, meta.subtitle].filter(Boolean).join(": ")],
    ["journal", kind === "article" ? meta.host || "" : ""],
    ["booktitle", kind === "chapter" ? [meta.host, meta.hostSubtitle].filter(Boolean).join(": ") : ""],
    ["year", yearOf(meta.pubyear)],
    ["volume", meta.volume || ""],
    ["number", meta.issue || (kind === "book" ? meta.seriesNumber || "" : "")],
    ["series", meta.seriesTitle || ""],
    ["pages", meta.pages || ""],
    ["address", meta.place || ""],
    ["publisher", meta.publisher || ""],
    ["note", presentCitation(meta.citation || "")],
    ["rights", DATA_RIGHTS],
    ["source", source],
  ];
  const body = fields
    .filter(([, value]) => value)
    .map(([key, value]) => `  ${key} = {${brace(value)}},`)
    .join("\n");
  const key = (meta.id || "bhb").replace(/[^A-Za-z0-9-]+/g, "-");
  return `@${BIB[kind]}{${key},\n${body}\n}\n`;
}

function ris(hit: Hit, source: string): string {
  const meta = hit.meta;
  const kind = kindOf(meta.kind);
  const range = pageRange(meta.pages);
  const lines = [`TY  - ${RIS[kind]}`];
  for (const person of people(meta.authors)) lines.push(`AU  - ${risName(person)}`);
  if (kind === "chapter") {
    for (const person of people(meta.hostEditors)) lines.push(`A2  - ${risName(person)}`);
  }
  push(lines, "TI", [meta.title, meta.subtitle].filter(Boolean).join(": "));
  if (kind === "article") push(lines, "JO", meta.host);
  if (kind === "article" || kind === "chapter") push(lines, "T2", [meta.host, meta.hostSubtitle].filter(Boolean).join(": "));
  push(lines, "VL", meta.volume);
  // RIS has no field for a series number, so the series statement keeps it, as printed.
  push(lines, "T3", [meta.seriesTitle, meta.seriesNumber].filter(Boolean).join(", "));
  push(lines, "IS", meta.issue);
  push(lines, "SP", range.start);
  push(lines, "EP", range.end);
  push(lines, "PY", yearOf(meta.pubyear));
  push(lines, "CY", meta.place);
  push(lines, "PB", meta.publisher);
  push(lines, "N1", presentCitation(meta.citation || ""));
  push(lines, "N1", DATA_RIGHTS);
  push(lines, "ID", meta.id);
  push(lines, "DB", source);
  lines.push("ER  - ");
  return `${lines.join("\r\n")}\r\n`;
}

function mods(hit: Hit, source: string): string {
  const meta = hit.meta;
  const parts: string[] = [
    `<?xml version="1.0" encoding="utf-8"?>`,
    `<mods xmlns="http://www.loc.gov/mods/v3" xmlns:xlink="http://www.w3.org/1999/xlink" version="3.8">`,
    `  <titleInfo>`,
    `    <title>${xml(meta.title || "")}</title>`,
  ];
  if (meta.subtitle) parts.push(`    <subTitle>${xml(meta.subtitle)}</subTitle>`);
  parts.push(`  </titleInfo>`);
  for (const person of people(meta.authors)) parts.push(modsName(person, "author"));
  if (meta.host || meta.volume || meta.issue || meta.pages) {
    parts.push(`  <relatedItem type="host">`);
    if (meta.host || meta.hostSubtitle) {
      parts.push(`    <titleInfo>`);
      if (meta.host) parts.push(`      <title>${xml(meta.host)}</title>`);
      if (meta.hostSubtitle) parts.push(`      <subTitle>${xml(meta.hostSubtitle)}</subTitle>`);
      parts.push(`    </titleInfo>`);
    }
    for (const person of people(meta.hostEditors)) parts.push(modsName(person, "editor", "    "));
    if (meta.volume || meta.issue || meta.pages) {
      parts.push(`    <part>`);
      if (meta.volume) parts.push(`      <detail type="volume"><number>${xml(meta.volume)}</number></detail>`);
      if (meta.issue) parts.push(`      <detail type="issue"><number>${xml(meta.issue)}</number></detail>`);
      const range = pageRange(meta.pages);
      if (range.start) {
        parts.push(`      <extent unit="pages">`);
        parts.push(`        <start>${xml(range.start)}</start>`);
        if (range.end) parts.push(`        <end>${xml(range.end)}</end>`);
        parts.push(`      </extent>`);
      }
      parts.push(`    </part>`);
    }
    parts.push(`  </relatedItem>`);
  }
  if (meta.place || meta.publisher || meta.pubyear) {
    parts.push(`  <originInfo>`);
    if (meta.place) parts.push(`    <place><placeTerm type="text">${xml(meta.place)}</placeTerm></place>`);
    if (meta.publisher) parts.push(`    <publisher>${xml(meta.publisher)}</publisher>`);
    const year = yearOf(meta.pubyear);
    if (year) parts.push(`    <dateIssued>${xml(year)}</dateIssued>`);
    parts.push(`  </originInfo>`);
  }
  if (meta.extent) parts.push(`  <physicalDescription><extent>${xml(meta.extent)}</extent></physicalDescription>`);
  if (meta.seriesTitle || meta.seriesNumber) {
    parts.push(`  <relatedItem type="series">`);
    if (meta.seriesTitle) parts.push(`    <titleInfo><title>${xml(meta.seriesTitle)}</title></titleInfo>`);
    if (meta.seriesNumber) parts.push(`    <part><detail type="volume"><number>${xml(meta.seriesNumber)}</number></detail></part>`);
    parts.push(`  </relatedItem>`);
  }
  if (meta.kind) parts.push(`  <genre authority="local">${xml(meta.kind)}</genre>`);
  if (meta.id) parts.push(`  <identifier type="bhb">${xml(meta.id)}</identifier>`);
  parts.push(`  <recordInfo><recordContentSource>${xml(source)}</recordContentSource></recordInfo>`);
  if (meta.citation) parts.push(`  <note type="printed citation">${xml(presentCitation(meta.citation))}</note>`);
  parts.push(`  <accessCondition type="use and reproduction" xlink:href="https://creativecommons.org/licenses/by-nc/4.0/">CC BY-NC 4.0</accessCondition>`);
  parts.push(`</mods>`, ``);
  return parts.join("\n");
}

function modsName(person: Name, role: string, indent = "  "): string {
  const lines = [`${indent}<name type="personal">`];
  lines.push(`${indent}  <namePart type="family">${xml(person.family)}</namePart>`);
  if (person.given) lines.push(`${indent}  <namePart type="given">${xml(person.given)}</namePart>`);
  lines.push(`${indent}  <role><roleTerm type="text">${role}</roleTerm></role>`);
  lines.push(`${indent}</name>`);
  return lines.join("\n");
}

function people(line: string | undefined): Name[] {
  if (!line?.trim()) return [];
  const sides = line.split(" & ");
  const raw = sides.length === 1 ? splitComma(sides[0]) : [...splitComma(sides.slice(0, -1).join(" & ")), sides.at(-1) || ""];
  return raw.map(parseName).filter((person) => person.family);
}

function splitComma(text: string): string[] {
  return text.split(", ").map((part) => part.trim()).filter(Boolean);
}

function parseName(text: string): Name {
  const match = text.trim().match(/^(.*)\(([^)]*)\)\s*$/);
  if (!match) return { family: text.trim(), given: "" };
  return { family: match[1].trim(), given: match[2].trim() };
}

function bibName(person: Name): string {
  return person.given ? `${person.family}, ${person.given}` : person.family;
}

function risName(person: Name): string {
  return person.given ? `${person.family}, ${person.given}` : person.family;
}

function kindOf(kind: string | undefined): keyof typeof BIB {
  if (kind && kind in BIB) return kind as keyof typeof BIB;
  return "other";
}

function yearOf(value: string | undefined): string {
  return value?.match(/\d{4}/)?.[0] || "";
}

function pageRange(pages: string | undefined): { start: string; end: string } {
  if (!pages?.trim()) return { start: "", end: "" };
  const match = pages.trim().match(/^(.+?)\s*[-–—]\s*(.+)$/);
  if (!match) return { start: pages.trim(), end: "" };
  return { start: match[1].trim(), end: match[2].trim() };
}

function push(lines: string[], tag: string, value: string | undefined): void {
  if (value?.trim()) lines.push(`${tag}  - ${value.replace(/\s+/g, " ").trim()}`);
}

function brace(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll("{", "\\{").replaceAll("}", "\\}");
}

function xml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}
