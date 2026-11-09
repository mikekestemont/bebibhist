// The deploy's search checks, run locally before a data release: builds the index from build/records.jsonl and the
// site, serves it as Pages would (vite preview) and runs tests/search-checks.mjs against it.
//   npm run verify             (index, build, checks)
//   npm run verify -- --no-index   (the index in public/ is already built from these records)
import { spawn } from "node:child_process";

const PORT = 4173;
// Under /bebibhist/, as GitHub Pages serves it; the checks refuse a site served at the root.
const base = `http://localhost:${PORT}/bebibhist/`;

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: "inherit" });
    child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`${command} ${args.join(" ")}: exit ${code}`))));
  });
}

async function waitFor(url, seconds) {
  for (let i = 0; i < seconds; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`${url} did not answer within ${seconds} s`);
}

if (!process.argv.includes("--no-index")) await run("npm", ["run", "index"]);
await run("npm", ["run", "build"]);
const preview = spawn("npx", ["vite", "preview", "--port", String(PORT), "--strictPort", "--base", "/bebibhist/"], { stdio: "ignore" });
// With the port taken (another preview still running), vite stops at once and the checks would test that other
// server instead: stop here and say so (9 Nov 2026).
let exited = null;
preview.on("exit", (code) => { exited = code; });
try {
  await new Promise((resolve) => setTimeout(resolve, 3000));
  if (exited !== null) throw new Error(`vite preview stopped (exit ${exited}): is port ${PORT} taken by another server?`);
  await waitFor(base, 60);
  await run("npm", ["run", "check", "--", base]);
} finally {
  preview.kill();
}
