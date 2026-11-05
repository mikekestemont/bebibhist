// The deploy's search checks, run locally before a data release: builds the index from build/records.jsonl and the
// site, serves it as Pages would (vite preview) and runs tests/search-checks.mjs against it.
//   npm run verify             (index, build, checks)
//   npm run verify -- --no-index   (the index in public/ is already built from these records)
import { spawn } from "node:child_process";

const PORT = 4173;
const base = `http://localhost:${PORT}/`;

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
const preview = spawn("npx", ["vite", "preview", "--port", String(PORT), "--strictPort"], { stdio: "ignore" });
try {
  await waitFor(base, 60);
  await run("npm", ["run", "check", "--", base]);
} finally {
  preview.kill();
}
