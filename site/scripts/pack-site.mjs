// Packs the site that `npm run verify` built and checked (site/dist) for the data release, so that the Pages
// workflow publishes it instead of building it again on GitHub's runner (24 Nov 2026: with 290,000 records the
// runner's build took over an hour, the Mac's about 20 minutes).
//   npm run verify && npm run pack     → build/release/site-dist.tar.gz, uploaded with the release
// The pack names what it was built from (dist/build-info.json): the git trees of site/ and data/curated/ and the
// records' SHA-256. The workflow deploys it only when these match the commit it runs and the release's records.
import { execFileSync } from "node:child_process";
import { createReadStream, existsSync } from "node:fs";
import { readFile, writeFile, mkdir, stat } from "node:fs/promises";
import { createHash } from "node:crypto";

const root = new URL("../../", import.meta.url).pathname;
const dist = `${root}site/dist`;
const records = `${root}build/records.jsonl`;
const out = `${root}build/release/site-dist.tar.gz`;
const git = (...args) => execFileSync("git", ["-C", root, ...args], { encoding: "utf8" }).trim();
const fail = (message) => { console.error(`pack: ${message}`); process.exit(1); };

const dirty = git("status", "--porcelain", "--", "site", "data/curated");
if (dirty) fail(`site/ or data/curated/ has changes not committed; commit them, then build and pack again:\n${dirty}`);
if (!existsSync(`${dist}/index.html`)) fail("no site/dist: run npm run verify first");
if (!existsSync(`${dist}/index-source.json`)) fail("site/dist has no index-source.json: run npm run verify (with the index) first");
const source = JSON.parse(await readFile(`${dist}/index-source.json`, "utf8"));
const hash = createHash("sha256");
for await (const chunk of createReadStream(records)) hash.update(chunk);
const recordsSha = hash.digest("hex");
if (source.records_sha256 !== recordsSha) fail("the index in site/dist was built from other records than build/records.jsonl: run npm run verify again");
// The site's build must be newer than its code: a build made before the last commit of site/ is refused.
const built = (await stat(`${dist}/index.html`)).mtimeMs / 1000;
const changed = Number(git("log", "-1", "--format=%ct", "--", "site", "data/curated"));
if (built < changed) fail("site/dist is older than the last commit of site/ or data/curated/: run npm run verify (or npm run build) again");
const info = {
  site_tree: git("rev-parse", "HEAD:site"),
  curated_tree: git("rev-parse", "HEAD:data/curated"),
  records_sha256: recordsSha,
  entries: source.entries,
  commit: git("rev-parse", "HEAD"),
  packed: new Date().toISOString(),
};
await writeFile(`${dist}/build-info.json`, JSON.stringify(info, null, 1) + "\n");
await mkdir(`${root}build/release`, { recursive: true });
// macOS tar would add "._" files for extended attributes, which would land on the site as files of their own.
execFileSync("tar", ["--no-mac-metadata", "-czf", out, "-C", dist, "."], { stdio: "inherit", env: { ...process.env, COPYFILE_DISABLE: "1" } });
console.log(`pack: ${out} (${Math.round((await stat(out)).size / 1e6)} MB), site ${info.site_tree.slice(0, 10)}, data ${info.curated_tree.slice(0, 10)}, records ${recordsSha.slice(0, 10)}`);
