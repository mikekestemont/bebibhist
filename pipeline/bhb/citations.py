"""The citation clean-up pass: a language model splits a printed citation into fields (decision of 31 Oct 2026).

The model reads ``printed`` and returns the record's fields as JSON, under a fixed schema; it copies text as printed
and lists suspected OCR errors separately, so nothing it proposes replaces the printed text. Requests go through
OpenRouter, only to providers that neither train on nor retain the data, with the model version and prompt pinned;
every answer is cached in ``build/cache/citations/``.

Before a full run, ``bhb citations pilot`` measures a model against an answer key: entries matched to a Crossref DOI,
whose title, authors, journal, volume, issue, pages and year are known independently of our parser. The parser is
scored on the same key, so the pilot shows per field whether the model is better, and at what cost.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from bhb.textutil import fold

API = "https://openrouter.ai/api/v1/chat/completions"
REFERER = "https://github.com/mikekestemont/bebibhist"
# Raised whenever the prompt or the schema changes, so cached answers of an older version are not reused.
PROMPT_VERSION = "1"

_NULLABLE_TEXT = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "persons", "title", "subtitle", "title_translated", "host", "publishers", "year", "extent",
                 "series", "note", "language", "ocr_fixes"],
    "properties": {
        "type": {"type": "string", "enum": ["article", "chapter", "book", "journal-issue", "review", "other"]},
        "persons": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["family", "given", "role"],
            "properties": {"family": {"type": "string"}, "given": _NULLABLE_TEXT,
                           "role": {"type": "string", "enum": ["author", "editor", "translator"]}}}},
        "title": {"type": "string"},
        "subtitle": _NULLABLE_TEXT,
        "title_translated": _NULLABLE_TEXT,
        "host": {"type": ["object", "null"], "additionalProperties": False,
                 "required": ["title", "volume", "issue", "year", "pages"],
                 "properties": {key: _NULLABLE_TEXT for key in ("title", "volume", "issue", "year", "pages")}},
        "publishers": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["place", "name"],
            "properties": {"place": _NULLABLE_TEXT, "name": _NULLABLE_TEXT}}},
        "year": {"type": ["integer", "null"]},
        "extent": _NULLABLE_TEXT,
        "series": {"type": ["object", "null"], "additionalProperties": False, "required": ["title", "number"],
                   "properties": {"title": {"type": "string"}, "number": _NULLABLE_TEXT}},
        "note": _NULLABLE_TEXT,
        "language": {"type": ["string", "null"], "description": "ISO 639-1 code of the title's language"},
        "ocr_fixes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["printed", "corrected"],
            "properties": {"printed": {"type": "string"}, "corrected": {"type": "string"}}}},
    },
}

SYSTEM = """You split one entry of the Bibliography of Belgian History (Bibliographie de l'Histoire de Belgique / \
Bibliografie van de Geschiedenis van België) into fields. Entries are in French, Dutch, German, English or Latin, and \
were digitised from print with OCR.

Rules:
- Copy every value exactly as printed: do not translate, expand abbreviations, modernise spelling or fix OCR errors \
in the fields. Journal names stay abbreviated as printed ("Hand. van de Soc. d'Émulation te Brugge").
- Names are printed as "Family (Given)"; "e.a." or "et al." adds no person. "(éd.)", "(ed.)", "(red.)", "(dir.)" \
mark editors. "s.n." is no person.
- An article or chapter has a host: the journal or the collected volume ("In:", "Dans:"). Its volume, issue, year \
and pages go in host; a chapter's volume title goes in host.title.
- A title in square brackets after the title is a translation: put it in title_translated.
- A bilingual imprint ("Bruxelles, X; Brussel, Y") gives two publishers.
- Text after " — " or " - " at the end that is no part of the title (a summary, contents, a comment) goes in note.
- year is the year of publication as an integer.
- ocr_fixes lists only words that are clearly OCR errors ("Seivias" for "Scivias", "terrrein"), with the correction; \
leave it empty when in doubt. Never list a historical or regional spelling."""


@dataclass
class Answer:
    fields: dict
    model: str
    provider: str | None
    cost: float | None


def _key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set OPENROUTER_API_KEY to the OpenRouter key; it is never stored in the repository.")
    return key


def request_body(printed: str, model: str) -> dict:
    return {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": printed}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "citation", "strict": True, "schema": SCHEMA}},
        # Only providers that neither train on nor retain prompts, at full or fp8 precision, that honour the schema.
        "provider": {"data_collection": "deny", "zdr": True, "quantizations": ["bf16", "fp16", "fp8"], "require_parameters": True},
        "usage": {"include": True},
    }


def ask(printed: str, model: str, cache: Path) -> Answer:
    """One citation through the model, from the cache when it was asked before with this model and prompt."""
    name = hashlib.sha1(f"{model}\n{PROMPT_VERSION}\n{printed}".encode()).hexdigest()
    path = cache / f"{name}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        body = json.dumps(request_body(printed, model)).encode()
        headers = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json", "HTTP-Referer": REFERER, "X-Title": "bebibhist"}
        for attempt in range(5):
            try:
                with urllib.request.urlopen(urllib.request.Request(API, data=body, headers=headers), timeout=120) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 4:
                    raise
                time.sleep(3 * (attempt + 1))
        cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    content = data["choices"][0]["message"]["content"]
    return Answer(json.loads(content), data.get("model", model), data.get("provider"), (data.get("usage") or {}).get("cost"))


# --- the answer key: entries matched to a Crossref DOI --------------------------------------------------------------

def key_from_crossref(item: dict) -> dict:
    """The fields a Crossref item fixes, in the shape the scoring compares."""
    title = " ".join(item.get("title") or [])
    subtitle = " ".join(item.get("subtitle") or [])
    year = None
    for name in ("published-print", "issued", "published-online"):
        parts = (item.get(name) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    return {
        "title": ": ".join(part for part in (title, subtitle) if part),
        "families": sorted(fold(person.get("family", "")) for person in item.get("author") or [] if person.get("family")),
        "host": " ".join(item.get("container-title") or []),
        "volume": item.get("volume"),
        "issue": item.get("issue"),
        "first_page": _first_page(item.get("page")),
        "year": year,
    }


_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _number(value) -> str | None:
    """A volume or issue as a comparable number: Roman numerals read, leading words and zeros dropped."""
    text = fold(str(value or ""))
    match = re.search(r"\b([ivxlcdm]+|\d+)\b", text)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return str(int(token))
    total = 0
    for index, char in enumerate(token):
        value_ = _ROMAN[char]
        total += -value_ if index + 1 < len(token) and _ROMAN[token[index + 1]] > value_ else value_
    return str(total)


def _first_page(pages) -> str | None:
    match = re.match(r"\D*(\d+)", str(pages or ""))
    return match.group(1) if match else None


def fields_of_record(record) -> dict:
    """Our parser's fields, in the same shape as the model's."""
    host = record.host
    return {
        "title": ": ".join(part for part in (record.title, record.subtitle) if part),
        "persons": [{"family": person.family, "role": person.role} for person in record.persons],
        "host": {"title": host.title, "volume": host.volume, "issue": host.issue, "pages": host.pages} if host else None,
        "year": record.year,
    }


def fields_of_answer(fields: dict) -> dict:
    host = fields.get("host")
    return {
        "title": ": ".join(part for part in (fields.get("title"), fields.get("subtitle")) if part),
        "persons": fields.get("persons") or [],
        "host": host,
        "year": fields.get("year"),
    }


def score(fields: dict, key: dict) -> dict[str, bool | None]:
    """Per field: right, wrong, or None when the key does not fix it. Titles may differ in case and punctuation;
    authors are compared by family name; volume, issue and first page as numbers."""
    host = fields.get("host") or {}
    authors = sorted(fold(person["family"]) for person in fields.get("persons") or [] if person.get("role", "author") == "author")
    result: dict[str, bool | None] = {
        "title": fuzz.ratio(fold(fields.get("title") or ""), fold(key["title"])) >= 95 if key["title"] else None,
        "authors": authors == key["families"] if key["families"] else None,
        "volume": _number(host.get("volume")) == _number(key["volume"]) if key["volume"] else None,
        "issue": _number(host.get("issue")) == _number(key["issue"]) if key["issue"] else None,
        "first_page": _first_page(host.get("pages")) == key["first_page"] if key["first_page"] else None,
        "year": fields.get("year") == key["year"] if key["year"] else None,
    }
    return result
