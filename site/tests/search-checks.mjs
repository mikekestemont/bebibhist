// Searches that must keep working, run against a built site before every deploy:
//   npx vite preview --port 4173 --base /bebibhist/   (then)   npm run check -- http://localhost:4173/bebibhist/
// Each check opens a fresh page, as a first visitor would. Counts are ranges, so a new data release does not break
// them; a check also fails when its first search takes longer than LIMIT_MS, and when the page or its search worker
// reports an error or misses a file of the search index.
//
// The site must be served under a path, as GitHub Pages serves it (/bebibhist/): at the root, a file looked for at
// the root is found, and the checks once passed while no search resolved on the published site (8 Nov 2026).
import { chromium } from "playwright";

const base = (process.argv[2] || "http://localhost:4173/bebibhist/").replace(/\/?$/, "/");
if (new URL(base).pathname === "/") {
  console.error(`Serve the site under a path, as GitHub Pages does (vite preview --base /bebibhist/), not at ${base}`);
  process.exit(2);
}
const LIMIT_MS = 20000;

const checks = [
  // A plain word, the search that hung on the live site when the worker looked for the index at the root.
  { name: "a plain word (bruaene)", hash: "#/search?q=bruaene", count: [60, 150], contains: /Van Bruaene/ },
  { name: "a word between two index chunks (béguinages)", hash: "#/search?q=b%C3%A9guinages", count: [1900, 2400], first: /b[ée]guin|begijn/i },
  { name: "another such word (abbaye, also through the title translations)", hash: "#/search?q=abbaye", count: [3800, 5200] },
  { name: "without the title translations (gewoonterecht)", hash: "#/search?q=gewoonterecht&tr=off", count: [5, 12] },
  { name: "optional function words (guibert de gembloux)", hash: "#/search?q=guibert%20de%20gembloux", count: [10, 30], contains: /Guibert of Gembloux/ },
  { name: "author search (Rider)", hash: "#/search?q=rider&field=author", count: [10, 30], contains: /Galbert of Bruges/ },
  { name: "author search (Tollebeek)", hash: "#/search?q=tollebeek&field=author", count: [100, 200] },
  // A name as an author link writes it is that person: not an entry whose Paul and whose Bertrand are two people.
  // Sébastien's feedback, 9 Nov 2026: an entry that prints no year shows the year of the data, marked as supplied;
  // and the year chart is as wide as the slider's track.
  { name: "a supplied year where none is printed (Rogghé, Eeklo)", hash: "#/search?q=rogghe%20silexdrager", count: [1, 5], contains: /Silexdrager[^]*\[1953\]/ },
  { name: "the year chart as wide as its slider", hash: "#/search?q=gent", selector: ".years .hist", sameWidth: ".years .handles .track" },
  // A hand correction (data/curated/corrections.csv): the 2004 volume names him Johan.
  { name: "a corrected author (Deploige (Jeroen), Interiorización)", hash: "#/search?q=Deploige%20(Jeroen)&field=author&per=100", count: [25, 70], contains: /Interiorisaci/ },
  // A translation copied from a neighbouring title (plan §4h): "Deploige" found four other Vatican articles of 1979.
  { name: "no hits through a copied translation (Deploige)", hash: "#/search?q=deploige&per=100", count: [30, 80], lacks: /course à la guerre|nonciature Micara|question romaine/ },
  { name: "a person by name (Bertrand (Paul))", hash: "#/search?q=Bertrand%20(Paul)&field=author", count: [15, 30], lacks: /Bertrand \(Jean-Pierre\)/ },
  { name: "publication-year range (gent, 1990–1999)", hash: "#/search?q=gent&from=1990&to=1999", count: [500, 4000] },
  { name: "subject and period filters", hash: "#/search?theme=religious&period=medieval", count: [800, 3000] },
  { name: "a record page (split chapter)", hash: "#/record/bhb%3A1996-13322-c5", selector: "main h1", contains: /Galbert/ },
  { name: "similar publications", hash: "#/similar/bhb%3Avs-1252259", selector: ".result", atLeast: 5 },
  // The classification's three parts (I., II., III.), with their names.
  { name: "browse by subject", hash: "#/browse", selector: ".tree > li", atLeast: 3, contains: /Bibliogra(?:f|ph)/ },
  // A subject of the classification, from the subject tree or a record's tag; a subject holds its sub-subjects.
  { name: "a subject of the classification (De financiën)", hash: "#/search?subject=III.D.2.b.5.", count: [150, 400] },
  { name: "a subject with its sub-subjects (Het economische leven, 1789–)", hash: "#/search?subject=III.D.2.b.", count: [7000, 11000] },
  { name: "place filter (Gent, indexed and from titles)", hash: "#/search?place=nis%3A44021", count: [2400, 3400] },
  { name: "a place suggested from the title", hash: "#/record/bhb%3A1995-11621", selector: ".tag-link.tag-suggested", contains: /Gh?ent|Gand/ },
  { name: "map of places", hash: "#/map", selector: ".map .place", atLeast: 1000 },
  { name: "journal filter (Biekorf, all spellings)", hash: "#/search?journal=t%3Abiekorf&journalTitle=Biekorf", count: [1500, 2200] },
  { name: "a matched DOI on a record page", hash: "#/record/bhb%3Avs-1180580", selector: "a.derived[href^='https://doi.org/']", contains: /10\.1484/ },
  // A word that is not in the index finds nothing at once (it used to match every word with its prefix, in 11 s).
  { name: "did you mean (vanthemse)", hash: "#/search?q=vanthemse&field=author", selector: ".did-you-mean", contains: /Vanthemsche/, limitMs: 5000 },
];

const browser = await chromium.launch();
let failed = 0;
for (const check of checks) {
  const page = await browser.newPage();
  const started = Date.now();
  let problem = "";
  // Errors of the page and of Pagefind's worker (whose console and requests Playwright reports on the page too),
  // and files of the search index that could not be fetched.
  const errors = [];
  const note = (text) => errors.push(String(text).split("\n")[0]);
  page.on("pageerror", (error) => note(`page error: ${error.message}`));
  page.on("console", (message) => message.type() === "error" && note(`console: ${message.text()}`));
  page.on("worker", (worker) => worker.on("console", (message) => message.type() === "error" && note(`worker: ${message.text()}`)));
  page.on("response", (response) => response.url().includes("/pagefind/") && response.status() >= 400 && note(`${response.status()} ${response.url()}`));
  page.on("requestfailed", (request) => request.url().includes("/pagefind/") && note(`failed ${request.url()}`));
  try {
    await page.goto(base + check.hash);
    if (check.count) {
      await page.waitForSelector(".count", { timeout: LIMIT_MS });
      const text = await page.textContent(".count");
      const count = Number((text || "").replace(/[^\d]/g, ""));
      if (count < check.count[0] || count > check.count[1]) problem = `count ${count} outside ${check.count.join("–")}`;
      if (!problem && check.first) {
        const first = await page.textContent(".result .citation");
        if (!check.first.test(first || "")) problem = `first hit "${(first || "").slice(0, 60)}" does not match ${check.first}`;
      }
      if (!problem && check.contains) {
        const all = (await page.locator(".result .citation").allTextContents()).join(" ");
        if (!check.contains.test(all)) problem = `no hit matches ${check.contains}`;
      }
      if (!problem && check.lacks) {
        const all = (await page.locator(".result .citation").allTextContents()).join(" ");
        if (check.lacks.test(all)) problem = `a hit matches ${check.lacks}`;
      }
    } else {
      await page.waitForSelector(check.selector, { timeout: check.limitMs || LIMIT_MS });
      if (check.atLeast) {
        const found = await page.locator(check.selector).count();
        if (found < check.atLeast) problem = `${found} × ${check.selector}, expected at least ${check.atLeast}`;
      }
      if (!problem && check.sameWidth) {
        const width = async (selector) => (await page.locator(selector).first().boundingBox())?.width ?? 0;
        const [one, two] = [await width(check.selector), await width(check.sameWidth)];
        if (Math.abs(one - two) > 2) problem = `${check.selector} is ${Math.round(one)} px wide, ${check.sameWidth} ${Math.round(two)} px`;
      }
      if (!problem && check.contains) {
        const text = await page.textContent(check.selector);
        if (!check.contains.test(text || "")) problem = `"${(text || "").slice(0, 60)}" does not match ${check.contains}`;
      }
    }
  } catch (error) {
    problem = String(error.message || error).split("\n")[0];
  }
  if (errors.length) problem = errors[0] + (problem ? ` (then: ${problem})` : "");
  const took = Date.now() - started;
  if (!problem && took > LIMIT_MS) problem = `took ${took} ms`;
  console.log(`${problem ? "FAIL" : "ok  "} ${check.name} (${took} ms)${problem ? ` — ${problem}` : ""}`);
  failed += problem ? 1 : 0;
  await page.close();
}
await browser.close();
if (failed) {
  console.error(`${failed} of ${checks.length} search checks failed`);
  process.exit(1);
}
console.log(`all ${checks.length} search checks passed`);
