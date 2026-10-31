// Searches that must keep working, run against a built site before every deploy:
//   npm run check -- http://localhost:4173/
// Each check opens a fresh page, as a first visitor would. Counts are ranges, so a new data release does not break
// them; a check also fails when its first search takes longer than LIMIT_MS.
import { chromium } from "playwright";

const base = (process.argv[2] || "http://localhost:4173/").replace(/\/?$/, "/");
const LIMIT_MS = 20000;

const checks = [
  { name: "a word between two index chunks (béguinages)", hash: "#/search?q=b%C3%A9guinages", count: [1900, 2400], first: /b[ée]guin|begijn/i },
  { name: "another such word (abbaye)", hash: "#/search?q=abbaye", count: [3000, 4200] },
  { name: "optional function words (guibert de gembloux)", hash: "#/search?q=guibert%20de%20gembloux", count: [10, 30], contains: /Guibert of Gembloux/ },
  { name: "author search (Rider)", hash: "#/search?q=rider&field=author", count: [10, 30], contains: /Galbert of Bruges/ },
  { name: "author search (Tollebeek)", hash: "#/search?q=tollebeek&field=author", count: [100, 200] },
  { name: "publication-year range (gent, 1990–1999)", hash: "#/search?q=gent&from=1990&to=1999", count: [500, 4000] },
  { name: "subject and period filters", hash: "#/search?theme=religious&period=medieval", count: [800, 3000] },
  { name: "a record page (split chapter)", hash: "#/record/bhb%3A1996-13322-c5", selector: "main h1", contains: /Galbert/ },
  { name: "similar publications", hash: "#/similar/bhb%3Avs-1252259", selector: ".result", atLeast: 5 },
  { name: "browse by subject", hash: "#/browse", selector: ".tree > li", atLeast: 8 },
  { name: "place filter (Gent, indexed and from titles)", hash: "#/search?place=nis%3A44021", count: [2400, 3400] },
  { name: "a place suggested from the title", hash: "#/record/bhb%3A1995-11621", selector: ".tag-link.tag-suggested", contains: /Gh?ent|Gand/ },
  { name: "map of places", hash: "#/map", selector: ".map .place", atLeast: 1000 },
  { name: "did you mean (vanthemse)", hash: "#/search?q=vanthemse&field=author", selector: ".did-you-mean", contains: /Vanthemsche/ },
];

const browser = await chromium.launch();
let failed = 0;
for (const check of checks) {
  const page = await browser.newPage();
  const started = Date.now();
  let problem = "";
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
    } else {
      await page.waitForSelector(check.selector, { timeout: LIMIT_MS });
      if (check.atLeast) {
        const found = await page.locator(check.selector).count();
        if (found < check.atLeast) problem = `${found} × ${check.selector}, expected at least ${check.atLeast}`;
      }
      if (!problem && check.contains) {
        const text = await page.textContent(check.selector);
        if (!check.contains.test(text || "")) problem = `"${(text || "").slice(0, 60)}" does not match ${check.contains}`;
      }
    }
  } catch (error) {
    problem = String(error.message || error).split("\n")[0];
  }
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
