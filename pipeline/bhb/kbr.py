"""The Belgian Bibliography of KBR (legal deposit), harvested through its OAI-PMH server, as an ISBN source.

KBR offers the set ``BelgianDataset`` (about 1.1 million records, Dublin Core) at ``opac.kbr.be/oaiserver.ashx``
(https://opac.kbr.be/belgian-bibliography.aspx). The harvest is stored page by page, gzipped, in
``build/external/kbr/`` and can be stopped and resumed: the last resumption token is kept. One request a second.
Only the ISBN and the link to the KBR record are taken over into the bibliography.
"""

from __future__ import annotations

import gzip
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from bhb.identifiers import USER_AGENT

OAI = "https://opac.kbr.be/oaiserver.ashx"
_RECORD = re.compile(r"<record>(.*?)</record>", re.S)
SET = "BelgianDataset"
INTERVAL = 1.0


_ISBN_FIELD = re.compile(r"<dc:identifier>(?:97[89])?\d{9}[\dXx]</dc:identifier>")


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


def harvest(folder: Path, progress=None) -> int:
    """Fetch the set page by page into ``folder``, resuming from the saved token; returns the pages fetched now."""
    folder.mkdir(parents=True, exist_ok=True)
    token_file = folder / "resumption-token.txt"
    pages = sorted(folder.glob("page-*.xml.gz"))
    token = token_file.read_text(encoding="utf-8").strip() if token_file.exists() else ""
    if pages and not token:
        return 0  # complete
    number = len(pages)
    fetched = 0
    while True:
        params = {"verb": "ListRecords", "resumptionToken": token} if token else {"verb": "ListRecords", "metadataPrefix": "oai_dc", "set": SET}
        url = f"{OAI}?{urllib.parse.urlencode(params)}"
        for attempt in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=120) as response:
                    text = response.read().decode("utf-8")
                break
            except (urllib.error.URLError, TimeoutError):
                if attempt == 5:
                    raise
                time.sleep(10 * (attempt + 1))
        number += 1
        fetched += 1
        (folder / f"page-{number:06d}.xml.gz").write_bytes(gzip.compress(kept(text).encode("utf-8")))
        found = re.search(r"<resumptionToken[^>]*>([^<]*)</resumptionToken>", text)
        token = found.group(1).strip() if found else ""
        token_file.write_text(token, encoding="utf-8")
        if progress and number % 100 == 0:
            progress(number)
        if not token:
            return fetched
        time.sleep(INTERVAL)


@dataclass
class Book:
    id: str
    title: str
    creators: list[str] = field(default_factory=list)
    publishers: list[str] = field(default_factory=list)
    isbn: list[str] = field(default_factory=list)
    year: int | None = None


_FIELD = re.compile(r"<dc:(\w+)[^>]*>(.*?)</dc:\1>", re.S)


def _isbn(value: str) -> str | None:
    digits = re.sub(r"[^0-9Xx]", "", value)
    return digits.upper() if len(digits) in (10, 13) else None


def books(folder: Path):
    """Every harvested record with an ISBN, as a ``Book`` (title without the statement of responsibility)."""
    import html

    for path in sorted(folder.glob("page-*.xml.gz")):
        for record in _RECORD.findall(gzip.decompress(path.read_bytes()).decode("utf-8")):
            book = Book(id="", title="")
            for tag, value in _FIELD.findall(record):
                value = html.unescape(value).strip()
                if tag == "title" and not book.title:
                    book.title = value.split(" / ")[0].strip()
                elif tag == "creator":
                    book.creators.append(value.split(".")[0].strip())
                elif tag == "publisher":
                    book.publishers.append(value)
                elif tag == "identifier":
                    if value.startswith("https://uurl.kbr.be/"):
                        book.id = value
                    elif (number := _isbn(value)) and number not in book.isbn:
                        book.isbn.append(number)
                elif tag == "date" and (year := re.search(r"(1[5-9]|20)\d{2}", value)):
                    book.year = int(year.group(0))
            if book.isbn and book.title:
                yield book
