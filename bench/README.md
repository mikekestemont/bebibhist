# Search benchmark

Static page that runs the P1 queries against `build/bench/` through the vendored
[sql.js-httpvfs](https://github.com/phiresky/sql.js-httpvfs) 0.8.12 (Apache-2.0; see `vendor/sql.js-httpvfs/LICENSE`).

```bash
cd pipeline
.venv/bin/python -m bhb bench build
.venv/bin/python -m bhb bench serve
```

Open `http://127.0.0.1:8765/bench/`. The page writes a JSON report into the last `<pre>`.
`bhb bench serve` answers `Range` with 206 responses; Python's `http.server` does not,
and the worker would otherwise download a whole 50 MB chunk per read. Add
`--latency-ms 150 --bytes-per-second 209715` to imitate the Chrome Fast 4G preset.
The measured result is in `docs/BENCHMARK.md`. The database chunks stay in `build/`
and are not committed.
