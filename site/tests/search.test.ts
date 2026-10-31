// Unit tests for the search helpers. Run with: node --experimental-strip-types --test tests/
import assert from "node:assert/strict";
import { test } from "node:test";

import { citationHtml, contentWords, editDistance, presentCitation, relaxedQuery, searchQuery, yearFilter } from "../src/lib/search.ts";

test("a year range matches any of its years, not all of them at once", () => {
  assert.deepEqual(yearFilter(1990, 1992), { any: ["1990", "1991", "1992"] });
  assert.deepEqual(yearFilter(0, 1947, 2026), { any: ["1945", "1946", "1947"] });
  assert.equal(yearFilter(0, 0), null);
});

test("function words are optional, except in an author search", () => {
  assert.equal(relaxedQuery("guibert de gembloux"), "guibert gembloux");
  assert.equal(relaxedQuery("de smet", "author"), null);
  assert.equal(relaxedQuery("de la"), null);
  assert.equal(relaxedQuery("gembloux"), null);
});

test("a field search prefixes every word, and a hyphen does not exclude a word", () => {
  assert.equal(searchQuery("Anne-Laure Van Bruaene", "author"), "au_Anne au_Laure au_Van au_Bruaene");
  assert.equal(searchQuery("béguinages"), "beguinages");
});

test("content words are folded and leave out function words", () => {
  assert.deepEqual(contentWords("Les béguinages de Gand"), ["beguinages", "gand"]);
});

test("edit distance counts a swap of two letters as one edit and stops at the limit", () => {
  assert.equal(editDistance("vanthemse", "vanthemsche", 2), 2);
  assert.equal(editDistance("tollebek", "tollebeek", 2), 1);
  assert.equal(editDistance("gnet", "gent", 1), 1);
  assert.equal(editDistance("pirenne", "brussel", 2), 3);
});

test("a doubled stop after an abbreviation is shown once, and cross-references are left out", () => {
  assert.equal(presentCitation("Dupont (A.). Titre. s.n.. [Cfr. n° 1234]"), "Dupont (A.). Titre. s.n.");
});

test("the volume's title is italic after In:, also after its editors", () => {
  const html = citationHtml(
    "Deploige (Jeroen). Political Assassination. In: Deploige (Jeroen), Deneckere (Gita). Mystifying the Monarch, 2006, pp. 35–54.",
    { title: "Political Assassination", host: "Mystifying the Monarch", kind: "chapter" },
  );
  assert.match(html, /<em>Mystifying the Monarch<\/em>/);
});

test("a journal title is italic after the article's title", () => {
  const html = citationHtml("Prims (Floris). Schilde. Antwerpiensia, 24, 53, p. 141–91.", { title: "Schilde", host: "Antwerpiensia", kind: "article" });
  assert.match(html, /Schilde\. <em>Antwerpiensia<\/em>, 24/);
});

test("an article's subtitle stays roman; only the journal is italic", () => {
  const html = citationHtml(
    "Kestemont (Mike). Collaborative authorship in the twelfth century: A stylometric study. In: Literary and Linguistic Computing, 30, 2015.",
    { title: "Collaborative authorship in the twelfth century", subtitle: "A stylometric study", host: "Literary and Linguistic Computing", kind: "article" },
  );
  assert.doesNotMatch(html, /<em>A stylometric study<\/em>/);
  assert.match(html, /<em>Literary and Linguistic Computing<\/em>/);
});
