"""Synthetic FTS5 database for the search-engine benchmark.

The database follows the site schema in the prototype spec: a records table,
an external-content FTS5 index, a narrow facet table and a multi-value facet
table. Titles are drawn from the built bibliography. The file is then split
into 50 MB chunks for sql.js-httpvfs.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bhb.paths import build_dir, repo_root

RARE_TERM = "zzqxrareterm"
CHUNK_BYTES = 50 * 1024 * 1024
PAGE_SIZE = 4096
REQUEST_CHUNK = 64 * 1024
PERIODS = ("aux", "general", "ancient", "medieval", "burgundian", "early-modern", "contemporary")
TYPES = ("article", "book", "chapter", "other")
LANGS = ("fr", "nl", "en", "de")
SOURCES = ("print-straive", "print-pdf", "vsmart")
JOURNALS = (
    "Revue belge de philologie et d'histoire",
    "Bijdragen en mededelingen betreffende de geschiedenis der Nederlanden",
    "Handelingen van de Koninklijke Commissie voor Geschiedenis",
    "Bulletin de la Commission royale d'Histoire",
    "Revue d'histoire ecclésiastique",
    "Belgisch tijdschrift voor nieuwste geschiedenis",
    "Revue belge d'histoire contemporaine",
    "Annales de la Société d'archéologie de Bruxelles",
)
PLACES = (
    "Bruxelles", "Brussel", "Gent", "Gand", "Antwerpen", "Anvers", "Liège", "Luik",
    "Leuven", "Louvain", "Brugge", "Bruges", "Namur", "Namen", "Mons", "Bergen",
)


def load_corpus(path: Path) -> list[tuple[str, str, str, str, str]]:
    """Return (title, persons, host, note, section) from a records JSON Lines file."""
    rows: list[tuple[str, str, str, str, str]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            data = json.loads(line)
            title = (data.get("title") or "").strip()
            if not title:
                continue
            persons = " ".join(
                " ".join(part for part in (person.get("family"), person.get("given")) if part)
                for person in data.get("persons") or []
            )
            host = ((data.get("host") or {}) or {}).get("title") or ""
            rows.append((title, persons, host or "", (data.get("note") or "")[:240], " ".join(data.get("section_path") or [])))
    if not rows:
        raise SystemExit(f"no titles in {path}")
    return rows


def build_database(
    corpus: list[tuple[str, str, str, str, str]],
    destination: Path,
    n: int = 270_000,
    seed: int = 2026,
) -> dict:
    """Write a synthetic database and its 50 MB chunks. Returns the config dict."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    rng = random.Random(seed)
    connection = sqlite3.connect(destination)
    connection.execute(f"PRAGMA page_size={PAGE_SIZE}")
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.executescript(
        """
        CREATE TABLE records (
            rowid INTEGER PRIMARY KEY,
            id TEXT UNIQUE,
            bgb_year INT,
            year INT,
            type TEXT,
            lang TEXT,
            source TEXT,
            display TEXT,
            printed TEXT,
            json TEXT
        );
        CREATE VIRTUAL TABLE fts USING fts5(
            title, persons, host, notes, section, places,
            content='',
            tokenize="unicode61 remove_diacritics 2",
            prefix='2 3'
        );
        CREATE TABLE facets (
            rowid INTEGER PRIMARY KEY,
            year INT,
            bgb_year INT,
            type TEXT,
            lang TEXT,
            source TEXT
        );
        CREATE INDEX facets_year ON facets(year);
        CREATE TABLE facet_multi (rowid INT, facet TEXT, value TEXT);
        CREATE INDEX facet_multi_fv ON facet_multi(facet, value, rowid);
        """
    )
    batch = 5_000
    for start in range(0, n, batch):
        size = min(batch, n - start)
        records = []
        fts_rows = []
        facets = []
        multi = []
        for offset in range(size):
            index = start + offset + 1
            title, persons, host, note, section = rng.choice(corpus)
            if index == 1:
                title = f"{title} {RARE_TERM}"
            year = rng.randint(1952, 2017)
            kind = rng.choice(TYPES)
            lang = rng.choice(LANGS)
            source = rng.choice(SOURCES)
            place = rng.choice(PLACES) if rng.random() < 0.5 else ""
            printed = f"{persons}. {title}. {host}".strip()[:600]
            records.append(
                (
                    index,
                    f"bhb:bench-{index}",
                    year,
                    year,
                    kind,
                    lang,
                    source,
                    printed,
                    printed,
                    json.dumps({"id": f"bhb:bench-{index}", "title": title}, ensure_ascii=False),
                )
            )
            fts_rows.append((index, title, persons, host, note, section, place))
            facets.append((index, year, year, kind, lang, source))
            multi.append((index, "period", rng.choice(PERIODS)))
            if kind == "article":
                multi.append((index, "journal", rng.choice(JOURNALS)))
            if place:
                multi.append((index, "place", place))
        connection.executemany(
            "INSERT INTO records (rowid, id, bgb_year, year, type, lang, source, display, printed, json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            records,
        )
        connection.executemany(
            "INSERT INTO fts (rowid, title, persons, host, notes, section, places) VALUES (?,?,?,?,?,?,?)",
            fts_rows,
        )
        connection.executemany("INSERT INTO facets VALUES (?,?,?,?,?,?)", facets)
        connection.executemany("INSERT INTO facet_multi VALUES (?,?,?)", multi)
        connection.commit()
        print(f"  {start + size}/{n}", flush=True)
    rare = connection.execute("SELECT count(*) FROM fts WHERE fts MATCH ?", (RARE_TERM,)).fetchone()[0]
    histoire = connection.execute("SELECT count(*) FROM fts WHERE fts MATCH 'histoire'").fetchone()[0]
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    connection.close()
    chunks = split_database(destination, destination.parent / "chunks")
    config = {
        "serverMode": "chunked",
        "requestChunkSize": REQUEST_CHUNK,
        "databaseLengthBytes": destination.stat().st_size,
        "serverChunkSize": CHUNK_BYTES,
        "urlPrefix": "/build/bench/chunks/bhb.sqlite.",
        "suffixLength": 3,
    }
    (destination.parent / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    summary = {
        "records": n,
        "rare_hits": rare,
        "histoire_hits": histoire,
        "page_size": page_size,
        "bytes": config["databaseLengthBytes"],
        "chunks": len(chunks),
    }
    (destination.parent / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def serve(port: int = 8765, latency_ms: int = 0, bytes_per_second: int = 0) -> None:
    """Serve the repository with HTTP range responses.

    ``sql.js-httpvfs`` reads the database in small ranges. Python's
    ``http.server`` answers those with the whole file, so this handler
    returns ``206 Partial Content``.
    """
    os.chdir(repo_root())

    class RangeHandler(SimpleHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = Path(self.translate_path(self.path.split("?", 1)[0]))
            header = self.headers.get("Range")
            if header is None or not path.is_file():
                super().do_GET()
                return
            size = path.stat().st_size
            start_text, _, end_text = header.removeprefix("bytes=").partition("-")
            start = int(start_text) if start_text else 0
            end = int(end_text) if end_text else size - 1
            end = min(end, size - 1)
            if start > end or start < 0:
                self.send_error(416, "Requested range not satisfiable")
                return
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(str(path)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            if latency_ms:
                time.sleep(latency_ms / 1000)
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining:
                    block = handle.read(min(remaining, 64 * 1024))
                    if not block:
                        break
                    if bytes_per_second:
                        time.sleep(len(block) / bytes_per_second)
                    self.wfile.write(block)
                    remaining -= len(block)

    server = ThreadingHTTPServer(("127.0.0.1", port), RangeHandler)
    print(f"benchmark server on http://127.0.0.1:{port}/bench/")
    server.serve_forever()


def split_database(database: Path, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("bhb.sqlite.*"):
        old.unlink()
    written: list[Path] = []
    with database.open("rb") as handle:
        index = 0
        while True:
            block = handle.read(CHUNK_BYTES)
            if not block:
                break
            path = folder / f"bhb.sqlite.{index:03d}"
            path.write_bytes(block)
            written.append(path)
            index += 1
    if not written:
        raise SystemExit(f"empty database {database}")
    return written
