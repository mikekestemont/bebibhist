// Unit tests for the search helpers. Run with: node --experimental-strip-types --test tests/
import assert from "node:assert/strict";
import { test } from "node:test";

import { AUTHOR_SHARE, authorQuery, authorsFirst, citationHtml, contentWords, editDistance, foundThroughTranslation, indexWords, presentCitation, relaxedQuery, searchQuery, yearFilter } from "../src/lib/search.ts";
import { nameWords } from "../src/lib/words.js";

test("a year range matches any of its years, not all of them at once", () => {
  assert.deepEqual(yearFilter(1990, 1992), { any: ["1990", "1991", "1992"] });
  assert.deepEqual(yearFilter(0, 1947, 2026), { any: ["1945", "1946", "1947"] });
  assert.equal(yearFilter(0, 0), null);
});

test("function words are optional, except in an author search", () => {
  assert.equal(relaxedQuery("guibert de gembloux"), "aw_guibert_ aw_gembloux_");
  assert.equal(relaxedQuery("de smet", "author"), null);
  assert.equal(relaxedQuery("de la"), null);
  assert.equal(relaxedQuery("gembloux"), null);
});

test("a field search tags every word, and a hyphen does not exclude a word", () => {
  assert.equal(searchQuery("Anne-Laure Van Bruaene", "author"), "au_anne_ au_laure_ au_vanbruaene_");
  assert.equal(searchQuery("béguinages"), "aw_beguinages_");
});

test("a word is matched whole: Brugge does not find bruggen, unless asked for", () => {
  assert.equal(searchQuery("Brugge"), "aw_brugge_");
  assert.equal(searchQuery("Brugge", "title"), "ti_brugge_");
  assert.equal(searchQuery("brugg*"), "aw_brugg");
  assert.equal(searchQuery("Brugge", "all", true, true), "aw_brugge");
  // A function word stays whole when the others find the words they begin.
  assert.equal(searchQuery("guibert de gembloux", "all", true, true), "aw_guibert aw_de_ aw_gembloux");
});

test("an author's particles join the name after them, as the index joins them", () => {
  assert.equal(searchQuery("van der Weyden", "author"), "au_vanderweyden_");
  assert.equal(searchQuery("Vander Weyden", "author"), "au_vanderweyden_");
  assert.equal(searchQuery("Vanderweyden", "author"), "au_vanderweyden_");
  assert.equal(searchQuery("Weyden", "author"), "au_weyden_");
  // Particles alone are the beginning of a name, not two words of two names (Derom & Van Doorne).
  assert.equal(searchQuery("van der", "author"), "au_vander");
  assert.equal(searchQuery("d'Otreppe", "author"), "au_dotreppe_");
  assert.deepEqual(nameWords("Dervaux-Van Ussel").map((item) => item.word), ["dervaux", "vanussel"]);
});

test("without the translations, all text and title search the record's own words only", () => {
  assert.equal(searchQuery("droit coutumier", "all", false), "og_droit_ og_coutumier_");
  assert.equal(searchQuery("gewoonterecht", "title", false), "ot_gewoonterecht_");
  assert.equal(searchQuery("Tollebeek", "author", false), "au_tollebeek_");
  assert.equal(relaxedQuery("guibert de gembloux", "all", false), "og_guibert_ og_gembloux_");
});

test("a hit through a translation needs the whole word in the translation only", () => {
  const words = { og: "les ponts de bruges", tw: "bruggen van brugge" };
  assert.equal(foundThroughTranslation(words, "bruggen"), true);
  assert.equal(foundThroughTranslation(words, "brugg"), false);
  assert.equal(foundThroughTranslation(words, "brugg", true), true);
  assert.equal(foundThroughTranslation(words, "ponts"), false);
  // A prefix that the record's own text has too ("brug…" in "bruges") is no hit through the translation.
  assert.equal(foundThroughTranslation(words, "brug", true), false);
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

test("a chapter printed without In: has its book in italics after its own title", () => {
  // Guy Vanthemsche, 10 Nov 2026.
  const citation = "Ortino (Sergio). La legislazione bancaria negli anni Trenta negli Stati Uniti e in Svizzera, Germania e Belgio. Banca e Industria fra le due guerre. Ricerca promossa dal Banco di Roma. Bologna, Il Mulino, 1981, pp. 349–400.";
  const html = citationHtml(citation, { title: "La legislazione bancaria negli anni Trenta negli Stati Uniti e in Svizzera, Germania e Belgio", host: "Banca e Industria fra le due guerre. Ricerca promossa dal Banco di Roma", kind: "chapter" });
  assert.match(html, /Belgio\. <em>Banca e Industria fra le due guerre\. Ricerca promossa dal Banco di Roma<\/em>\. Bologna/);
});

test("a two-digit year of the 1950s gets the full year in brackets, marked as supplied", () => {
  const citation = "Geldolf (W.). Een vredescongres te Brussel 103 jaar geleden. Nieuw Vlaams Tijdschrift, VI, 51, p. 185–195.";
  const html = citationHtml(citation, { title: "Een vredescongres te Brussel 103 jaar geleden", host: "Nieuw Vlaams Tijdschrift", kind: "article", pubyear: "1951" }, "", "", "", "", "", "Aangevuld");
  assert.match(html, /VI, 51 <span class="derived" title="Aangevuld">\[1951\]<\/span>, p\. 185/);
  // The full year printed, or the two digits standing twice, leave the line as printed.
  assert.doesNotMatch(citationHtml("Dupont (A.). Titre. Revue, 51, 1951, p. 3.", { pubyear: "1951" }), /\[1951\]/);
  assert.doesNotMatch(citationHtml("Dupont (A.). Titre. Revue, 51, 51, p. 3.", { pubyear: "1951" }), /\[1951\]/);
});

test("an article's subtitle stays roman; only the journal is italic", () => {
  const html = citationHtml(
    "Kestemont (Mike). Collaborative authorship in the twelfth century: A stylometric study. In: Literary and Linguistic Computing, 30, 2015.",
    { title: "Collaborative authorship in the twelfth century", subtitle: "A stylometric study", host: "Literary and Linguistic Computing", kind: "article" },
  );
  assert.doesNotMatch(html, /<em>A stylometric study<\/em>/);
  assert.match(html, /<em>Literary and Linguistic Computing<\/em>/);
});

test("a host missing from the export is left out of the line, not shown as a title", () => {
  const html = citationHtml("Vanthemsche (Guy). Transports. In: [host record not exported], 2008, p. 433-439.", { title: "Transports", host: "[host record not exported]", kind: "chapter" }, "", "", "", "[tijdschrift of boek niet in de export]", "Ontbreekt in de export.");
  assert.equal(html, "Vanthemsche (Guy). Transports. 2008, p. 433-439.");
  assert.ok(!html.includes("host record not exported"));
});

test("a hit found only through its title's translation says so", () => {
  const words = { og: "de gewoonte in het leenhof van brabant", tw: "la coutume cour feodale", ot: "de gewoonte in het leenhof van brabant", tt: "la coutume cour feodale" };
  assert.equal(foundThroughTranslation(words, "coutume féodale"), true);
  assert.equal(foundThroughTranslation(words, "leenhof"), false);
  assert.equal(foundThroughTranslation(words, "Brabant"), false);
  assert.equal(foundThroughTranslation({ og: "la coutume" }, "coutume"), false);
  assert.equal(foundThroughTranslation(undefined, "coutume"), false);
});

test("the index words of a record under each search tag", () => {
  const words = { og: "les ponts de bruges", tw: "bridges", ot: "les ponts", tt: "bridges", au: "dupont" };
  assert.deepEqual(indexWords(words, "og"), ["les", "ponts", "de", "bruges"]);
  assert.deepEqual(indexWords(words, "aw"), ["les", "ponts", "de", "bruges", "bridges"]);
  assert.deepEqual(indexWords(words, "ot"), ["les", "ponts"]);
  assert.deepEqual(indexWords(words, "ti"), ["les", "ponts", "bridges"]);
  assert.deepEqual(indexWords(words, "au"), ["dupont"]);
  assert.deepEqual(indexWords(words, "se"), []);
  assert.deepEqual(indexWords(undefined, "aw"), []);
});

test("a printed entry without any year shows the year of the data, in brackets and marked as supplied", () => {
  const html = citationHtml("Stengers (Jean). Quelques notes sur la genèse. Mél. G. Smets. Bruxelles, p. 1–20.", { pubyear: "1952" }, "", "", "", "", "", "", "Aangevuld");
  assert.match(html, /p\. 1–20 <span class="derived" title="Aangevuld">\[1952\]<\/span>\.$/);
  // A year of its own, even another one, is left as printed.
  assert.doesNotMatch(citationHtml("Dupont (A.). Titre. Liège, 1950, 12 p.", { pubyear: "1951" }, "", "", "", "", "", "", "x"), /\[1951\]/);
  assert.doesNotMatch(citationHtml("Dupont (A.). Titre. Liège, 12 p.", { pubyear: "" }, "", "", "", "", "", "", "x"), /\[/);
});

test("one-letter words are left out, as the index leaves them out", () => {
  assert.equal(searchQuery("l'abbaye de Villers"), "aw_abbaye_ aw_de_ aw_villers_");
  assert.equal(searchQuery("Jacquemin J.-P.", "author"), "au_jacquemin_");
  assert.equal(searchQuery("d'Otreppe", "author"), "au_dotreppe_");
});

test("a name searched in all text is also searched as the people's whole words, particles joined", () => {
  assert.equal(authorQuery("Vanthemsche"), "au_vanthemsche_");
  assert.equal(authorQuery("Guy Vanthemsche"), "au_guy_ au_vanthemsche_");
  assert.equal(authorQuery("van der Weyden"), "au_vanderweyden_");
  assert.equal(authorQuery("Jansen-Sieben"), "au_jansen_ au_sieben_");
  // A quoted phrase, a "*" or only particles is no name to look up.
  assert.equal(authorQuery('"De Smet"'), null);
  assert.equal(authorQuery("vanthem*"), null);
  assert.equal(authorQuery("van der"), null);
});

test("author hits come first only when they are a fair share of the hits (plan §4f, point 8)", () => {
  const hits = (ids: string[]) => ids.map((id) => ({ id }));
  // Vanthemsche: Bisschop's chapter in a volume he edited (bhb:vs-1250412) follows his own work.
  const found = hits(["bhb:vs-1250412", "a", "b", "c"]);
  assert.deepEqual(authorsFirst(found, new Set(["a", "b", "c"]))?.map((hit) => hit.id), ["a", "b", "c", "bhb:vs-1250412"]);
  // Gent: a few authors named Van Gent among thousands of entries on the town keep the order.
  const town = hits(Array.from({ length: 100 }, (_, i) => `g${i}`));
  assert.equal(authorsFirst(town, new Set(["g7", "g40", "g99"])), null);
  assert.ok(AUTHOR_SHARE > 0.14 && AUTHOR_SHARE < 0.44);
  // Nothing to move: every hit an author hit, or one alone.
  assert.equal(authorsFirst(hits(["a", "b"]), new Set(["a", "b"])), null);
  assert.equal(authorsFirst(hits(["a", "b", "c"]), new Set(["b"])), null);
});
