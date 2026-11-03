"""Harvesting KBR's Belgian Bibliography by date windows (OAI-PMH ``from``/``until``).

KBR's server pages a list by skipping to the cursor, so a page costs more the further it lies in the list: 6 seconds
at the start of the whole set, over a minute a third of the way in (November 2026). A window of datestamps is a list
of its own, so its pages stay near the start. The window from 1900 to now is halved until each part holds at most
``LIMIT`` records; the first page of a window that small is kept, a larger one is split and its page dropped.

A record that changes during the harvest moves to a later datestamp: the window after the planned end is harvested
last, so it is not lost; a record found twice is kept once (``bhb.kbr.books``). The state is saved after every page,
so the harvest can be stopped and resumed.

Only the standard library, and Python 3.8, so that it can run on its own on another machine:
``python3 kbr_harvest.py FOLDER``.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OAI = "https://opac.kbr.be/oaiserver.ashx"
SET = "BelgianDataset"
INTERVAL = 1.0
LIMIT = 10_000
START = datetime(1900, 1, 1, tzinfo=timezone.utc)
_RECORD = re.compile(r"<record>(.*?)</record>", re.S)
_SECOND = timedelta(seconds=1)


def kept(page: str) -> str:
    """The records worth keeping from a page: books (with an ISBN for the identifiers; without one, often a local
    society's publication, as a candidate for the recent years) and periodicals (for their ISSN). Maps, printed music
    and the like are left out; OAI-PMH cannot leave them out of the transfer."""
    records = []
    for record in _RECORD.findall(page):
        kind = re.search(r"<dc:type[^>]*>([^<]*)</dc:type>", record)
        kind = kind.group(1) if kind else ""
        if kind in ("Livre", "Périodique", "Journal"):
            records.append(f"<record>{record}</record>")
    return "\n".join(records)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _moment(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def fetcher(user_agent: str):
    """A function that asks the server and returns its answer; it waits and tries again on a network fault."""

    def fetch(params: dict) -> str:
        url = f"{OAI}?{urllib.parse.urlencode(params)}"
        for attempt in range(6):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": user_agent})
                with urllib.request.urlopen(request, timeout=300) as response:
                    return response.read().decode("utf-8")
            except (urllib.error.URLError, TimeoutError):
                if attempt == 5:
                    raise
                time.sleep(30 * (attempt + 1))
        raise AssertionError("unreachable")

    return fetch


def _answer(text: str) -> tuple[int, str]:
    """The size of the list and the token for its next page ("" on the last page). A window without records is an
    empty list; any other error stops the harvest."""
    error = re.search(r'<error code="([^"]*)"', text)
    if error:
        if error.group(1) == "noRecordsMatch":
            return 0, ""
        raise RuntimeError(f"OAI error: {text[error.start():error.start() + 300]}")
    found = re.search(r"<resumptionToken([^>]*)>([^<]*)</resumptionToken>", text)
    if not found:
        return len(_RECORD.findall(text)), ""
    size = re.search(r'completeListSize="(\d+)"', found.group(1))
    return (int(size.group(1)) if size else LIMIT), found.group(2).strip()


def harvest(folder: Path, fetch, limit: int = LIMIT, interval: float = INTERVAL, now=_now, log=print) -> int:
    """Fetch the set window by window into ``folder``, resuming from ``state.json``; returns the pages fetched now."""
    folder.mkdir(parents=True, exist_ok=True)
    state_file = folder / "state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
    else:
        state = {"end": _stamp(now()), "pending": [[_stamp(START), _stamp(now())]], "current": None, "done": [],
                 "final": False}
    fetched = 0

    def save() -> None:
        temporary = state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=1), encoding="utf-8")
        temporary.replace(state_file)

    def write(start: str, number: int, text: str) -> None:
        name = f"page-{start.replace('-', '').replace(':', '')}-{number:04d}.xml.gz"
        (folder / name).write_bytes(gzip.compress(kept(text).encode("utf-8")))

    while True:
        current = state["current"]
        if current is None:
            if not state["pending"]:
                if state["final"]:
                    return fetched
                # What changed while the harvest ran has a datestamp after the planned end.
                state["final"] = True
                state["pending"] = [[state["end"], _stamp(now())]]
                continue
            start, end = state["pending"][0]
            begin, stop = _moment(start), _moment(end)
            text = fetch({"verb": "ListRecords", "metadataPrefix": "oai_dc", "set": SET, "from": start,
                          "until": _stamp(stop - _SECOND)})
            fetched += 1
            size, token = _answer(text)
            state["pending"].pop(0)
            if size > limit and stop - begin > _SECOND:
                middle = _stamp(begin + (stop - begin) // 2)
                state["pending"][0:0] = [[start, middle], [middle, end]]
            else:
                write(start, 1, text)
                state["current"] = {"from": start, "until": end, "size": size, "page": 1, "token": token}
        else:
            text = fetch({"verb": "ListRecords", "resumptionToken": current["token"]})
            fetched += 1
            current["page"] += 1
            _, current["token"] = _answer(text)
            write(current["from"], current["page"], text)
        current = state["current"]
        if current is not None and not current["token"]:
            state["done"].append([current["from"], current["until"], current["size"], current["page"]])
            state["current"] = None
            records = sum(window[2] for window in state["done"])
            log(f"  {current['from']} – {current['until']}: {current['size']} records, {current['page']} pages; "
                f"{records} records in {len(state['done'])} windows, {len(state['pending'])} windows to go",
                flush=True)
        save()
        time.sleep(interval)


if __name__ == "__main__":
    contact = os.environ.get("BHB_CONTACT", "").strip()
    agent = "bebibhist/0.1 (https://github.com/mikekestemont/bebibhist" + (f"; mailto:{contact})" if contact else ")")
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "kbr")
    pages = harvest(target, fetcher(agent))
    print(f"kbr: {pages} pages fetched now → {target}", flush=True)
