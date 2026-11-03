"""The harvest by date windows, against a small server that pages three records at a time."""

import gzip
from datetime import datetime, timezone

from bhb.kbr import books
from bhb.kbr_harvest import harvest

PAGE = 3


def record(number, stamp, kind="Livre"):
    return (f"<record><header><identifier>KBR{number}</identifier><datestamp>{stamp}</datestamp></header><metadata>"
            f"<dc:title>Title {number}</dc:title><dc:type>{kind}</dc:type>"
            f"<dc:identifier>https://uurl.kbr.be/bib/{number}</dc:identifier></metadata></record>")


class Server:
    def __init__(self, records):
        self.records = records  # (number, datestamp, kind)
        self.asked = []

    def __call__(self, params):
        self.asked.append(params)
        if "resumptionToken" in params:
            start, until, offset = params["resumptionToken"].split("|")
        else:
            start, until, offset = params["from"], params["until"], "0"
        found = sorted((r for r in self.records if start <= r[1] <= until), key=lambda r: r[0])
        if not found:
            return '<OAI-PMH><error code="noRecordsMatch">none</error></OAI-PMH>'
        offset = int(offset)
        page = "".join(record(*r) for r in found[offset:offset + PAGE])
        nxt = f"{start}|{until}|{offset + PAGE}" if offset + PAGE < len(found) else ""
        token = f'<resumptionToken completeListSize="{len(found)}" cursor="{offset}">{nxt}</resumptionToken>'
        return f"<OAI-PMH><ListRecords>{page}{token}</ListRecords></OAI-PMH>"


def clock(*moments):
    queue = [datetime.fromisoformat(m).replace(tzinfo=timezone.utc) for m in moments]
    return lambda: queue.pop(0) if len(queue) > 1 else queue[0]


def numbers(folder):
    return sorted(book.number for book in books(folder))


RECORDS = [(n, f"2025-{1 + n % 12:02d}-{1 + n % 28:02d}T10:00:00Z", "Livre") for n in range(1, 41)]


def test_windows_are_split_until_small_and_every_record_is_found(tmp_path):
    server = Server(RECORDS + [(99, "2025-03-01T00:00:00Z", "Carte")])
    harvest(tmp_path, server, limit=8, interval=0, now=clock("2026-01-01T00:00:00"), log=lambda *a, **k: None)
    assert numbers(tmp_path) == [str(n) for n in sorted(range(1, 41), key=str)]
    # No page is asked for deep in a large list.
    assert all(int(p["resumptionToken"].split("|")[2]) < 8 for p in server.asked if "resumptionToken" in p)


def test_the_harvest_resumes_where_it_stopped(tmp_path):
    server = Server(RECORDS)

    class Stop(Exception):
        pass

    def failing(params):
        if len(server.asked) == 12:
            raise Stop
        return server(params)

    try:
        harvest(tmp_path, failing, limit=8, interval=0, now=clock("2026-01-01T00:00:00"), log=lambda *a, **k: None)
    except Stop:
        pass
    harvest(tmp_path, server, limit=8, interval=0, now=clock("2026-01-01T00:00:00"), log=lambda *a, **k: None)
    assert numbers(tmp_path) == [str(n) for n in sorted(range(1, 41), key=str)]
    full = Server(RECORDS)
    harvest(tmp_path / "again", full, limit=8, interval=0, now=clock("2026-01-01T00:00:00"), log=lambda *a, **k: None)
    assert len(server.asked) <= len(full.asked) + 1  # one page asked twice at most


def test_a_record_changed_during_the_harvest_is_found_once_in_its_later_window(tmp_path):
    server = Server(list(RECORDS))
    moved = False

    def changing(params):
        nonlocal moved
        if not moved and len(server.asked) == 5:
            # Record 7 is edited after the planned end: it leaves its window before that window is harvested.
            server.records = [r for r in server.records if r[0] != 7] + [(7, "2026-01-02T09:00:00Z", "Livre")]
            moved = True
        return server(params)

    harvest(tmp_path, changing, limit=8, interval=0,
            now=clock("2026-01-01T00:00:00", "2026-01-01T00:00:00", "2026-01-03T00:00:00"), log=lambda *a, **k: None)
    assert numbers(tmp_path) == [str(n) for n in sorted(range(1, 41), key=str)]
    assert server.asked[-1]["from"] == "2026-01-01T00:00:00Z"  # the window after the planned end


def test_only_books_and_periodicals_are_kept(tmp_path):
    server = Server([(1, "2025-01-01T00:00:00Z", "Livre"), (2, "2025-01-01T00:00:00Z", "Carte"),
                     (3, "2025-01-01T00:00:00Z", "Périodique")])
    harvest(tmp_path, server, interval=0, now=clock("2026-01-01T00:00:00"), log=lambda *a, **k: None)
    text = "".join(gzip.decompress(p.read_bytes()).decode() for p in tmp_path.glob("page-*.xml.gz"))
    assert "KBR1<" in text and "KBR3<" in text and "KBR2<" not in text
