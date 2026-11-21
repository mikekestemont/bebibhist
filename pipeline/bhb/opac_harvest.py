"""Records from the State Archives' public catalogue (Axiell Webopac Air 4.5, https://biblio.arch.be/airwebopac/).

The catalogue serves any record of V-Smart by its number, the ``N`` of our ``bhb:vs-N`` and of the export's
``_4630 Bib:2:N`` (checked 21 Nov 2026: ``bhb:vs-1193686``, missing from the export, is TNTL). It answers with the
display text of its "Full" template (title, authors, imprint, the note "BGB-BHB 2012", the host line, the BHB code),
not with the export profile's fields.

A record is fetched once and kept gzipped as ``<folder>/<N>.xml.gz``, so a harvest can be stopped and resumed and
the parsing redone offline. The server is the State Archives' own and old: one request at a time, ``INTERVAL``
seconds apart, longer when it answers slowly, and a pause after a fault.

Only the standard library, like ``bhb.kbr_harvest``.
"""

from __future__ import annotations

import gzip
import html
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://biblio.arch.be/airwebopac/"
PROFILE = "BHBBGB"
INTERVAL = 5.0
_ELEMENT = re.compile(r"<Label>([^<]*)</Label><Data><!\[CDATA\[(.*?)\]\]></Data>", re.S)
# Index links in the display text: #!#Uindex04^key^Shown#!# or #!#.278.11290***Uindex15$^key^Shown#!#
_LINK = re.compile(r"#!#[^#^]*\^[^^]*\^(.*?)#!#", re.S)


class Session:
    """A visitor's session: the catalogue answers a record request only after the page and its search set-up are
    loaded, as a browser does (an empty answer otherwise)."""

    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.opener = None
        self.token = ""

    def open(self) -> None:
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.opener.addheaders = [("User-Agent", self.user_agent), ("Referer", f"{BASE}www.main.cls?surl={PROFILE}"),
                                  ("X-Requested-With", "XMLHttpRequest")]
        page = self._get(f"www.main.cls?surl={PROFILE}")
        found = {key: re.search(rf"{key} = '([^']+)'", page) for key in ("sessionID", "profileID", "viewID")}
        if not all(found.values()):
            raise RuntimeError("the catalogue's page has no session")
        self.token, profile, view = (found[key].group(1) for key in ("sessionID", "profileID", "viewID"))
        time.sleep(1)
        self._get(f"www.content.cls?action=getApplications&v={view}&p={profile}&SIDTKN={self.token}")
        time.sleep(1)
        self._get(f"Service.Search.cls?language=dut&SIDTKN={self.token}")

    def _get(self, path: str) -> str:
        with self.opener.open(BASE + path, timeout=60) as response:
            return response.read().decode("utf-8", "replace")

    def post(self, params: dict) -> str:
        if not self.token:
            self.open()
        data = urllib.parse.urlencode({**params, "SIDTKN": self.token}).encode()
        request = urllib.request.Request(BASE + "Proxy.SearchRequest.cls", data=data,
                                         headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        with self.opener.open(request, timeout=120) as response:
            return response.read().decode("utf-8", "replace")


def record_params(number: int) -> dict:
    return {"fu": "BibSearch", "Application": "Bib", "RequestType": "RecordNumber", "Database": "2",
            "Request": str(number), "TemplateId": "Iguana_Full", "ExportByTemplate": "Full", "LinkToWord": "0",
            "Language": "dut", "Profile": PROFILE, "Namespace": "0"}


def has_record(text: str) -> bool:
    return "<BibDocument>" in text


def harvest(numbers, folder: Path, session, interval: float = INTERVAL, sleep=time.sleep, clock=time.monotonic,
            log=print) -> dict:
    """Fetch the records not yet in ``folder``; returns counts. An empty answer gets a new session and one more try
    (the session may have expired); a network fault waits a minute, then longer; five faults in a row stop."""
    folder.mkdir(parents=True, exist_ok=True)
    counts = {"cached": 0, "fetched": 0, "empty": 0}
    faults = 0
    todo = [n for n in numbers if not (folder / f"{n}.xml.gz").exists()]
    counts["cached"] = len(numbers) - len(todo)
    for position, number in enumerate(todo, 1):
        for attempt in range(2):
            try:
                started = clock()
                text = session.post(record_params(number))
                took = clock() - started
            except (urllib.error.URLError, TimeoutError, ConnectionError) as fault:
                faults += 1
                if faults >= 5:
                    raise RuntimeError(f"five faults in a row, last at record {number}: {fault}") from fault
                log(f"  fault at {number} ({fault}); waiting {60 * faults} s", flush=True)
                sleep(60 * faults)
                session.token = ""
                continue
            faults = 0
            if has_record(text) or attempt == 1:
                break
            session.token = ""  # empty: open a new session and ask once more
            sleep(interval)
        else:
            continue
        if has_record(text):
            (folder / f"{number}.xml.gz").write_bytes(gzip.compress(text.encode("utf-8")))
            counts["fetched"] += 1
        else:
            counts["empty"] += 1
            log(f"  {number}: no record", flush=True)
        if position % 25 == 0:
            log(f"  {position}/{len(todo)} done", flush=True)
        # A slow answer means a busy server: wait longer before the next one.
        sleep(interval + 2 * max(0.0, took - 1.0))
    return counts


def clean(value: str) -> str:
    value = value.replace("]]><![CDATA[", "")  # one field can hold several CDATA blocks (holdings notes)
    value = _LINK.sub(lambda m: m.group(1), value)
    value = re.sub(r"<br\s*/?>", "\n", value)
    value = re.sub(r"</?q>", "", value)
    value = html.unescape(value)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def parse(text: str) -> dict:
    """The display fields of one record, by label without the "Full" prefix (``MainTitle``, ``Author``, ``Imprint``,
    ``Note``, ``Series`` for the host line, ``Keyword``, ...), plus its number and material type codes."""
    record: dict = {}
    number = re.search(r"<Id>2\.(\d+)</Id>", text)
    record["number"] = int(number.group(1)) if number else None
    for label, value in _ELEMENT.findall(text):
        label = label.removeprefix("Full")
        if label == "CoverA":
            record.update({k.lower(): v for k, v in re.findall(r"(MATTYPE|BIBTYPE|PUBTYPE)=([^!]*)", value)})
        else:
            record[label] = clean(value)
    note = record.get("Note", "")
    year = re.search(r'"BGB-BHB (\d{4})"', note)
    record["bgb_year"] = int(year.group(1)) if year else None
    return record


def parse_folder(folder: Path) -> list[dict]:
    return [parse(gzip.decompress(path.read_bytes()).decode("utf-8"))
            for path in sorted(folder.glob("*.xml.gz"), key=lambda p: int(p.name.split(".")[0]))]


def missing_hosts(records_path: Path) -> list[int]:
    """The numbers of host records that entries point to (``host.id`` = ``bhb:vs-N``) but the build lacks."""
    known, wanted = set(), set()
    with records_path.open(encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            known.add(record["id"])
            host = (record.get("host") or {}).get("id") or ""
            if host.startswith("bhb:vs-"):
                wanted.add(host)
    return sorted(int(h.removeprefix("bhb:vs-")) for h in wanted - known)
