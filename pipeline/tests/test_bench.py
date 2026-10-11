import json
import sqlite3

from bhb.bench import RARE_TERM, build_database


def test_synthetic_database_is_searchable_and_chunked(tmp_path):
    corpus = [
        ("Histoire de la ville", "Dupont Jean", "Revue belge", "", "III. Histoire"),
        ("Een geschiedenis van Gent", "Peeters Jan", "", "note", "II. Algemeen"),
    ]
    summary = build_database(corpus, tmp_path / "bhb.sqlite", n=40, seed=1)
    assert summary["rare_hits"] == 1
    assert summary["page_size"] == 4096
    assert summary["chunks"] == 1
    config = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert config["serverMode"] == "chunked"
    assert config["serverChunkSize"] == 50 * 1024 * 1024
    chunk = tmp_path / "chunks" / "bhb.sqlite.000"
    assert chunk.stat().st_size == (tmp_path / "bhb.sqlite").stat().st_size
    connection = sqlite3.connect(tmp_path / "bhb.sqlite")
    assert connection.execute("SELECT count(*) FROM fts WHERE fts MATCH ?", (RARE_TERM,)).fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM facets").fetchone()[0] == 40
    connection.close()
