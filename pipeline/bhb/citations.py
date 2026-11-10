"""The citation clean-up pass: a language model splits printed citations into fields (decision of 31 Oct 2026).

The model reads ``printed`` and returns the record's fields as JSON, under a fixed schema; it copies text as printed
and lists suspected OCR errors separately, so nothing it proposes replaces the printed text. Requests go through
OpenRouter with the model version and prompt pinned; every answer is cached in ``build/cache/citations/``. The data
are open, so providers that train on prompts are allowed (Mike, 3 Nov 2026); only full or fp8 precision is. EU models
are preferred, and go to their maker's EU endpoint (Mistral's).

Entries go in batches of about ten consecutive entries of one section (`docs/IMPLEMENTATION_PLAN.md` §5c), with the
section heading and the entry before them as context and the rules' hints (the journal behind an "Ibid.", the
local language, the entry a "cf. n°" points to). Every answer is checked: the same ids, in the same order; a batch
that skips or merges an entry is asked again entry by entry. A collected volume printed with its contents is a batch
on its own. Titles of entries the pass is not otherwise sent are translated in requests of their own, title only.

``bhb citations pilot`` measures a model against an answer key: entries matched to a Crossref DOI, whose title,
authors, journal, volume, issue, pages and year are known independently of our parser, and the interns' corrected
sheets of 1992 (books among them). The parser is scored on the same key, so the pilot shows per field whether the
model is better, and at what cost.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from bhb.textutil import fold

API = "https://openrouter.ai/api/v1/chat/completions"
REFERER = "https://github.com/mikekestemont/bebibhist"
# Raised whenever the prompt or the schema changes; the cache is keyed on the whole request anyway.
PROMPT_VERSION = "3"
# Full or fp8 precision only, and only providers that honour the schema; the data are open, so training is allowed.
PROVIDER = {"quantizations": ["bf16", "fp16", "fp8"], "require_parameters": True}
# EU models come first (Mike, 3 Nov 2026): Mistral's own endpoint in the EU, which states no precision but serves its
# own weights, so the precision filter does not apply to it.
HOME_PROVIDERS = {"mistralai/": "mistral/eu"}


def provider_for(model: str, provider: str | None = None) -> dict:
    """Routing for a model: one named provider (``deepinfra/fp8``, ``mistral/eu``) without fallbacks, the maker's own
    EU endpoint for an EU model, or else any provider at full or fp8 precision."""
    provider = provider or next((home for prefix, home in HOME_PROVIDERS.items() if model.startswith(prefix)), None)
    if provider:
        return {"only": [provider], "allow_fallbacks": False, "require_parameters": True}
    return PROVIDER
BATCH_SIZE = 10

_TEXT = {"type": "string"}
_NULLABLE_TEXT = {"type": ["string", "null"]}
_PERSON = {"type": "object", "additionalProperties": False, "required": ["family", "given", "role"],
           "properties": {"family": _TEXT, "given": _NULLABLE_TEXT,
                          "role": {"type": "string", "enum": ["author", "editor", "translator"]}}}
_PUBLISHER = {"type": "object", "additionalProperties": False, "required": ["place", "name"],
              "properties": {"place": _NULLABLE_TEXT, "name": _NULLABLE_TEXT}}


def _object(properties: dict, nullable: bool = False) -> dict:
    return {"type": ["object", "null"] if nullable else "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}


ENTRY = _object({
    "id": _TEXT,
    "type": {"type": "string", "enum": ["article", "chapter", "book", "journal-issue", "review", "other"]},
    "persons": {"type": "array", "items": _PERSON},
    "title": _TEXT,
    "subtitle": _NULLABLE_TEXT,
    "title_translated": _NULLABLE_TEXT,
    "host": _object({key: _NULLABLE_TEXT for key in ("title", "title_full", "volume", "issue", "year", "pages")}, nullable=True),
    "publishers": {"type": "array", "items": _PUBLISHER},
    "year": {"type": ["integer", "null"]},
    "extent": _NULLABLE_TEXT,
    "series": _object({"title": _TEXT, "number": _NULLABLE_TEXT}, nullable=True),
    "note": _NULLABLE_TEXT,
    "language": {"type": "array", "items": _TEXT, "description": "ISO 639-1 codes of the languages the title is in"},
    "translations": _object({"nl": _NULLABLE_TEXT, "fr": _NULLABLE_TEXT, "en": _NULLABLE_TEXT}),
    "editions": {"type": "array", "items": _object({
        "title": _TEXT, "subtitle": _NULLABLE_TEXT, "editors": {"type": "array", "items": _PERSON},
        "publishers": {"type": "array", "items": _PUBLISHER}, "year": {"type": ["integer", "null"]},
        "extent": _NULLABLE_TEXT, "language": {"type": "array", "items": _TEXT}})},
    "contents": {"type": "array", "items": _object({
        "persons": {"type": "array", "items": _PERSON}, "title": _TEXT, "pages": _NULLABLE_TEXT, "edition": {"type": "integer"}})},
    "ocr_fixes": {"type": "array", "items": _object({"printed": _TEXT, "corrected": _TEXT})},
})
SCHEMA = _object({"entries": {"type": "array", "items": ENTRY}})
TITLES = _object({"titles": {"type": "array", "items": _object(
    {"id": _TEXT, "nl": _TEXT, "fr": _TEXT, "en": _TEXT})}})

SYSTEM = """You split entries of the Bibliography of Belgian History (Bibliographie de l'Histoire de Belgique / \
Bibliografie van de Geschiedenis van België, 1952–2017) into fields. Entries are in French, Dutch, German, English \
or Latin, and most were digitised from print with OCR.

You get the section heading, sometimes the entry printed before (context only: do not answer for it), and the \
entries, each after its id in square brackets, sometimes with hints from earlier processing. Answer with one object \
per id, in the same order: never skip, merge or split an entry.

Rules:
- Copy every value exactly as printed: do not translate, expand abbreviations, modernise spelling or fix OCR errors \
in the fields. Journal names stay abbreviated as printed ("Hand. van de Soc. d'Émulation te Brugge").
- Names are printed as "Family (Given)"; "e.a." or "et al." adds no person. "(éd.)", "(ed.)", "(red.)", "(dir.)", \
"(uitg.)" mark editors. "s.n." is no person. "Id." or "Idem" in place of a name is the person of the entry before.
- An article or chapter has a host: the journal or the collected volume ("In:", "Dans:"). Its volume, issue, year \
and pages go in host; a chapter's volume title goes in host.title. "Ibid." as journal is the journal of the entry \
before: put that journal's name in host.title, as printed there (a hint may give it).
- A place followed by a publisher ("Bruxelles, Crédit communal", "Bussum, Uitg. P. Brand") is an imprint, not a \
host: the entry is a book (or a journal issue), and the imprint goes in publishers. A bilingual imprint \
("Bruxelles, X; Brussel, Y") gives two publishers.
- extent is the whole pagination as printed ("xv–293 p.", "2 vol.", "210 pp."), never the format (8°), the \
illustrations or the price.
- A series in parentheses ("(Verhandelingen KVAB, 42)") goes in series, its title and number apart.
- A title in square brackets after the title is the editors' translation: put it in title_translated, never in \
title or subtitle (a hint may give it).
- host.title_full is the journal's or volume's name written out in full, in its own language, only when you know \
the journal and are certain of every word ("Hand. van het Genootsch. voor Gesch. te Brugge" → "Handelingen van het \
Genootschap voor Geschiedenis te Brugge"); else null. It never replaces host.title.
- Text after " — " or " - " at the end that is no part of the title (a summary, contents, a comment) goes in note.
- year is the year of publication as an integer.
- language lists the languages the title (with subtitle) is written in, as ISO 639-1 codes: two only for a title \
printed in two languages. The editors' bracketed translation is not a language of publication.
- translations gives the title (with subtitle, joined by ": ") translated into Dutch, French and English: fill \
every one of the three that is not a language of the title, for every entry; null only for a language the title is \
already in. Keep names of persons and places as printed, except well-known places that \
have a name in that language (Luik/Liège, Gent/Gand, Bergen/Mons). Use the terms of historical scholarship \
(schepenbank → échevinage / bench of aldermen; mainmorte → dode hand / mortmain).
- contents: only when the entry lists the contributions of a collected volume, one item each (authors, title, \
pages, edition: the index of its edition in editions, else 0). editions: only when one entry prints the same volume \
in two language editions, one item each. Otherwise both are empty.
- ocr_fixes lists only words that are clearly OCR errors ("Seivias" for "Scivias", "terrrein"), with the \
correction; leave it empty when in doubt. Never list a historical or regional spelling.

Two worked examples. Entries:
Section: I. Généralités › C. Travaux d'ensemble
Entry before (context only): Faider-Feytmans (G.). Adolphe Quetelet et les Beaux-Arts. Bull. de l'Ac. R. de B., \
Cl. des Beaux-Arts, 1974, 2, pp. 190–199.

[ex-1] Janssen (C.). Carmelkluis en Carmelwereld. [Ermitage de C. et monde du C.]. Bussum, Uitg. P. Brand, 1955, \
8°, 210 pp., 95 fr. — Esquisse historique de l'Ordre des Frères de N.-D.-du-Mont-Carmel.
    hint: the editors' bracketed translation: Ermitage de C. et monde du C.
[ex-2] Roberts-Jones (Philippe). Madou et Quetelet. Ibid., pp. 200–204.

Answer:
{"entries": [{"id": "ex-1", "type": "book", "persons": [{"family": "Janssen", "given": "C.", "role": "author"}], \
"title": "Carmelkluis en Carmelwereld", "subtitle": null, "title_translated": "Ermitage de C. et monde du C.", \
"host": null, "publishers": [{"place": "Bussum", "name": "Uitg. P. Brand"}], "year": 1955, "extent": "210 pp.", \
"series": null, "note": "Esquisse historique de l'Ordre des Frères de N.-D.-du-Mont-Carmel.", "language": ["nl"], \
"translations": {"nl": null, "fr": "Ermitage carmélitain et monde carmélitain", "en": "Carmelite hermitage and \
Carmelite world"}, "editions": [], "contents": [], "ocr_fixes": []}, {"id": "ex-2", "type": "article", "persons": \
[{"family": "Roberts-Jones", "given": "Philippe", "role": "author"}], "title": "Madou et Quetelet", "subtitle": \
null, "title_translated": null, "host": {"title": "Bull. de l'Ac. R. de B., Cl. des Beaux-Arts", "title_full": \
"Bulletin de la Classe des Beaux-Arts de l'Académie royale de Belgique", "volume": null, "issue": "2", "year": \
"1974", "pages": "200–204"}, "publishers": [], "year": 1974, "extent": null, "series": null, "note": null, \
"language": ["fr"], "translations": {"nl": "Madou en Quetelet", "fr": null, "en": "Madou and Quetelet"}, \
"editions": [], "contents": [], "ocr_fixes": []}]}"""

MARKUP = """

The entries come as the digitisation vendor's JATS mark-up of the printed text. The text between the tags is what \
was printed; the tags are the vendor's first guess and often wrong (an imprint tagged <source>, the format "8°" \
tagged <issue>, a price tagged <fpage>). Use them as hints only, judge every field from the text, and copy values \
from the text without tags."""

TRANSLATE = """You translate titles of publications on Belgian history, listed in the Bibliography of Belgian \
History, so that a reader can find them by searching in Dutch, French or English. For each id, give the title in \
Dutch (nl), French (fr) and English (en): always all three. Where the title is already in one of these languages, \
copy it unchanged for that language. The language in parentheses before the title was read by a machine and may be \
wrong; a title in German, Latin or another language is translated into all three.

Translate faithfully and plainly, the whole title with its subtitle; do not explain, shorten or add. Keep names of \
persons as printed. Places keep their printed name, except well-known places that have a name of their own in that \
language (Luik/Liège, Gent/Gand, Bergen/Mons, Antwerpen/Anvers, Brussel/Bruxelles/Brussels, Leuven/Louvain, \
Mechelen/Malines, Doornik/Tournai, Rijsel/Lille); any other place stays exactly as printed, even when a similar \
name exists. Use the terms of historical scholarship in each language, as in this glossary (Dutch / French / \
English):
schepenbank, schepenen / échevinage, échevins / bench of aldermen, aldermen; leenhof / cour féodale / feudal court; \
vierschaar / vierschaar, tribunal / court of justice; baljuw / bailli / bailiff; meier / mayeur / mayor; \
kasselrij / châtellenie / castellany; ambacht (a district of a castellany) / métier / ambacht; ambacht (a craft), \
gilde / métier, corporation / craft, guild; heerlijkheid / seigneurie / seigneury; proosdij / prévôté / \
provostship; costumen / coutumes / customary law; keure / keure, charte / charter; cijns / cens / quitrent; tol / \
tonlieu / toll; dode hand / mainmorte / mortmain; Staten / États / States; raadpensionaris / pensionnaire / \
pensionary.
A bracketed translation by the editors may follow the title: use it as a reference, and do not translate the \
brackets themselves. Answer with one object per id, in the same order."""


@dataclass
class Item:
    id: str
    printed: str
    hints: list[str] = field(default_factory=list)


@dataclass
class Batch:
    section: str | None
    before: str | None
    items: list[Item]
    markup: bool = False  # the items hold the vendor's JATS mark-up instead of the plain text


@dataclass
class Reply:
    """One request: its answer and what it cost."""
    content: dict | None
    model: str
    provider: str | None
    cost: float
    tokens_in: int
    tokens_out: int
    tokens_reasoning: int
    seconds: float
    cached: bool
    error: str | None = None


def _key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set OPENROUTER_API_KEY to the OpenRouter key; it is never stored in the repository.")
    return key


def batch_message(batch: Batch) -> str:
    lines = [f"Section: {batch.section or '—'}"]
    if batch.before:
        lines.append(f"Entry before (context only): {batch.before}")
    lines.append("")
    for item in batch.items:
        lines.append(f"[{item.id}] {item.printed}")
        lines.extend(f"    hint: {hint}" for hint in item.hints)
    return "\n".join(lines)


def request_body(system: str, user: str, schema: dict, model: str, reasoning: str | None = None,
                 name: str = "citations", provider: str | None = None) -> dict:
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 16000,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        "provider": provider_for(model, provider),
        "usage": {"include": True},
    }
    if reasoning:
        body["reasoning"] = {"effort": reasoning}
    return body


def call(body: dict, cache: Path) -> Reply:
    """One request, from the cache when this exact request was sent before."""
    name = hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = cache / f"{name}.json"
    cached = path.exists()
    seconds = 0.0
    if cached:
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        encoded = json.dumps(body).encode()
        headers = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json", "HTTP-Referer": REFERER, "X-Title": "bebibhist"}
        started = time.monotonic()
        data = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(urllib.request.Request(API, data=encoded, headers=headers), timeout=300) as response:
                    data = json.loads(response.read().decode("utf-8"))
                if "choices" in data and (data["choices"][0].get("finish_reason") != "error" or attempt >= 2):
                    break  # a provider's failure is asked twice more before it counts
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:300]
                if error.code not in (408, 429, 500, 502, 503, 504) or attempt == 4:
                    return Reply(None, body["model"], None, 0.0, 0, 0, 0, time.monotonic() - started, False, f"HTTP {error.code}: {detail}")
                if error.code == 429:  # the provider's rate limit: wait longer each time
                    time.sleep(min(120, 10 * 2 ** attempt))
                    continue
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                if attempt == 4:
                    return Reply(None, body["model"], None, 0.0, 0, 0, 0, time.monotonic() - started, False, str(error))
            time.sleep(3 * (attempt + 1))
        seconds = time.monotonic() - started
        if not data or "choices" not in data:
            return Reply(None, body["model"], None, 0.0, 0, 0, 0, seconds, False, json.dumps(data)[:300])
        data["_seconds"] = seconds
        # A provider's failure (Mistral ends a run of blank output with finish_reason "error") is not an answer: it is
        # not cached, so the next run asks again.
        if data["choices"][0].get("finish_reason") != "error":
            cache.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    usage = data.get("usage") or {}
    reply = Reply(None, data.get("model", body["model"]), data.get("provider"), float(usage.get("cost") or 0.0),
                  int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0),
                  int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
                  float(data.get("_seconds", seconds)), cached)
    message = data["choices"][0].get("message") or {}
    try:
        reply.content = json.loads(message.get("content") or "")
    except json.JSONDecodeError:
        reply.error = f"no JSON ({data['choices'][0].get('finish_reason')})"
    return reply


def ask_batch(batch: Batch, model: str, cache: Path, reasoning: str | None = None,
              provider: str | None = None) -> tuple[dict[str, dict], list[Reply]]:
    """The answers per id for one batch. A batch whose ids come back wrong is asked again entry by entry, each with
    the entry before it as context; an entry that fails alone too is left out."""
    system = SYSTEM + MARKUP if batch.markup else SYSTEM
    reply = call(request_body(system, batch_message(batch), SCHEMA, model, reasoning, provider=provider), cache)
    replies = [reply]
    entries = (reply.content or {}).get("entries") or []
    if [entry.get("id") for entry in entries] == [item.id for item in batch.items]:
        return {entry["id"]: entry for entry in entries}, replies
    if reply.content is not None:
        reply.error = reply.error or "ids do not match"
    if len(batch.items) == 1 or (reply.error or "").startswith("HTTP 4"):
        return {}, replies  # a refused request (a parameter the model does not take) fails alone as well
    answers: dict[str, dict] = {}
    before = batch.before
    for item in batch.items:
        single, more = ask_batch(Batch(batch.section, before, [item], batch.markup), model, cache, reasoning, provider)
        answers.update(single)
        replies.extend(more)
        before = item.printed
    return answers, replies


def ask_titles(items: list[Item], model: str, cache: Path, reasoning: str | None = None,
               provider: str | None = None) -> tuple[dict[str, dict], Reply]:
    """Translations of title-only items (``Item.printed`` holds the title, ``Item.hints`` the languages the local
    identifier read), checked per id like a batch. The model gives all three; a translation into a language of the
    title, or one that only copies the title, is dropped by rule."""
    user = "\n".join(f"[{item.id}] ({'+'.join(item.hints) or '?'}) {item.printed}" for item in items)
    reply = call(request_body(TRANSLATE, user, TITLES, model, reasoning, name="titles", provider=provider), cache)
    titles = (reply.content or {}).get("titles") or []
    if [title.get("id") for title in titles] != [item.id for item in items]:
        reply.error = reply.error or "ids do not match"
        return {}, reply
    found = {}
    for item, title in zip(items, titles):
        original = fold(re.sub(r"\s*\[.*?\]", "", item.printed))
        found[item.id] = {code: (None if code in item.hints or fold(title.get(code) or "") == original else (title.get(code) or "").strip() or None)
                          for code in ("nl", "fr", "en")}
    return found, reply


def markup_of(records: list) -> dict[str, str]:
    """Per STRAIVE entry, the inner mark-up of its ``<mixed-citation>``, entities resolved, from the raw JATS file."""
    import html

    wanted: dict[str, dict[str, str]] = {}
    for record in records:
        if record.source == "print-straive" and record.provenance.file and record.provenance.xml_id:
            wanted.setdefault(record.provenance.file, {})[record.provenance.xml_id] = record.id
    found: dict[str, str] = {}
    for path, ids in wanted.items():
        text = Path(path).read_text(encoding="utf-8")
        for match in re.finditer(r'<ref id="([^"]+)">.*?<mixed-citation[^>]*>(.*?)</mixed-citation>', text, re.S):
            if match.group(1) in ids:
                inner = re.sub(r"<([\w-]+)\s[^>]*>", r"<\1>", match.group(2))  # attributes add tokens, not meaning
                found[ids[match.group(1)]] = re.sub(r"\s+", " ", html.unescape(inner)).strip()
    return found


# --- batches in printed order --------------------------------------------------------------------------------------

_PAGE_RANGE = re.compile(r"\b(?:p|pp|blz|S)\.?\s*\d+\s*[-–]\s*\d+")
_IBID = re.compile(r"\b(?:Ibid|Ibidem)\b", re.IGNORECASE)
_CROSS = re.compile(r"\b(?:cf|zie|voir)\.?\s*n[°o]", re.IGNORECASE)


def is_collected_volume(printed: str) -> bool:
    """A volume printed with its contents: three page ranges or more in more than 500 characters (§5c)."""
    return len(printed) > 500 and len(_PAGE_RANGE.findall(printed)) >= 3


def hints_for(record, journals: dict[str, str], by_id: dict) -> list[str]:
    """What the rules already resolved, as hints: the model decides only where the rules stop."""
    hints = []
    if record.journal_id and record.journal_id in journals and _IBID.search(record.printed or ""):
        hints.append(f'"Ibid." is the journal {journals[record.journal_id]}')
    if record.title_translated and record.title_translated in (record.printed or ""):
        hints.append(f"the editors' bracketed translation: {record.title_translated}")
    if record.language_suggested:
        hints.append("language (read by a local identifier): " + ", ".join(record.language_suggested))
    if _CROSS.search(record.printed or ""):
        for target in record.cross_refs[:3]:
            other = by_id.get(target)
            if other is not None and other.printed:
                hints.append(f"{target.split('-')[-1]} refers to: {other.printed[:160]}")
    return hints


def make_batches(records: list, journals: dict[str, str], size: int = BATCH_SIZE) -> list[Batch]:
    """Consecutive entries of one section, ``size`` at a time, in printed order; a collected volume alone."""
    by_id = {record.id: record for record in records}
    batches: list[Batch] = []
    current: list = []
    before = None

    def flush() -> None:
        nonlocal current
        if current:
            batches.append(Batch(" › ".join(current[0].section_path) or None, before.printed if before else None,
                                 [Item(record.id, record.printed, hints_for(record, journals, by_id)) for record in current]))
            current = []

    previous = None
    for record in records:
        if not record.printed:
            continue
        new_section = previous is None or record.section_path != previous.section_path or record.bgb_year != previous.bgb_year
        if new_section or len(current) >= size or is_collected_volume(record.printed):
            flush()
            before = previous if not new_section else None
        current.append(record)
        if is_collected_volume(record.printed):
            flush()
            before = record
        previous = record
    flush()
    return batches


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
        "type": record.type,
        "title": ": ".join(part for part in (record.title, record.subtitle) if part),
        "persons": [{"family": person.family, "role": person.role} for person in record.persons],
        "host": {"title": host.title, "volume": host.volume, "issue": host.issue, "pages": host.pages} if host else None,
        "year": record.year,
    }


def tidy(answer: dict, printed: str | None = None, bgb_year: int | None = None) -> dict:
    """Faults of a model answer that have a fixed form, fixed by rule:
    - the editors' bracketed translation put in the subtitle goes to title_translated (Mistral Small 4 does this in
      about one entry in ten with a translation, hint or not);
    - a bracketed text printed after the host or imprint is a gloss ("[famille luxembourgeoise]"), not a translation;
    - a two-digit number taken for the issue that is the year of the volume ("Limburg, XXXI, 52", the 1950s) is the
      year;
    - an article has no publishers: a place printed with a journal ("Hautes Fagnes, XXXI, Verviers, 1965") belongs
      to the journal, and stays in the citation."""
    if answer.get("type") == "article" and answer.get("publishers"):
        answer = dict(answer, publishers=[])
    subtitle = (answer.get("subtitle") or "").strip()
    translated = (answer.get("title_translated") or "").strip()
    bracketed = subtitle.startswith("[") and subtitle.rstrip(" .").endswith("]")
    if subtitle and (bracketed or (translated and fold(subtitle.strip("[] .")) == fold(translated.strip("[] .")))):
        answer = dict(answer, subtitle=None, title_translated=translated or subtitle.strip(" .").strip("[]"))
        translated = answer["title_translated"]
    if printed and translated:
        at = printed.find("[" + translated.strip("[] .")[:20])
        anchors = [(answer.get("host") or {}).get("title")] + [p.get("place") or p.get("name") for p in answer.get("publishers") or []]
        starts = [printed.find(anchor[:15]) for anchor in anchors if anchor and printed.find(anchor[:15]) >= 0]
        if at >= 0 and starts and at > min(starts):
            answer = dict(answer, title_translated=None)
    host = answer.get("host")
    if bgb_year and host and re.fullmatch(r"\d{2}", str(host.get("issue") or "").strip()) and not host.get("year"):
        year = 1900 + int(host["issue"])
        if 0 <= bgb_year - year <= 2:
            answer = dict(answer, host=dict(host, issue=None, year=str(year)), year=answer.get("year") or year)
    return answer


def fields_of_answer(fields: dict) -> dict:
    """The model's fields in the shape of ``fields_of_record``; an article's year may stand in its host only."""
    host = fields.get("host")
    year = fields.get("year")
    if year is None and host and re.fullmatch(r"\d{4}", str(host.get("year") or "").strip()):
        year = int(host["year"])
    return {
        "type": fields.get("type"),
        "title": ": ".join(part for part in (fields.get("title"), fields.get("subtitle")) if part),
        "persons": fields.get("persons") or [],
        "host": host,
        "year": year,
    }


def combined(model: dict, parser: dict) -> dict:
    """The model's fields, with the parser's where the model gives none (§5c: rules and the pass together)."""
    host = dict(parser.get("host") or {})
    host.update({key: value for key, value in (model.get("host") or {}).items() if value})
    return {key: model.get(key) or parser.get(key) for key in parser} | {"host": host or None}


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


def score_gold(fields: dict, row) -> dict[str, bool | None]:
    """Per field against a corrected intern sheet (``bhb.gold.GoldRow``): title with subtitle, the first author's
    family name, the host as printed, the year, and book or not."""
    host = (fields.get("host") or {}).get("title") or ""
    persons = [person for person in fields.get("persons") or [] if person.get("role", "author") == "author"]
    return {
        "title": fuzz.ratio(fold(fields.get("title") or ""), fold(row.title)) >= 95 if row.title else None,
        "authors": bool(persons) and fold(persons[0]["family"]) == fold(row.surname) if row.surname else None,
        "host": fuzz.ratio(fold(host), fold(row.host_title)) >= 90 if row.host_title else None,
        "year": str(fields.get("year") or "") == row.year if row.year else None,
        "book": (fields.get("type") == "book") == (row.kind == "book") if row.kind else None,
    }


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def copied_values(answer: dict, printed: str) -> tuple[int, int]:
    """How many of an answer's copied values occur in the printed citation as they stand (case and spacing aside):
    title, subtitle, host title and pages, family names, places, publishers, extent. A value that does not occur was
    changed, expanded or made up — the rule says to copy."""
    text = _squeeze(printed)
    values = [answer.get("title"), answer.get("subtitle"), answer.get("extent")]
    values += [(answer.get("host") or {}).get(key) for key in ("title", "pages")]
    values += [person.get("family") for person in answer.get("persons") or []]
    values += [publisher.get(key) for publisher in answer.get("publishers") or [] for key in ("place", "name")]
    values = [_squeeze(value).rstrip(" .") for value in values if value]
    return sum(1 for value in values if value in text), len(values)


def missing_translations(answer: dict) -> int:
    """Translations the answer leaves out: one per language of nl, fr and en that the title is not already in."""
    own = set(answer.get("language") or [])
    translations = answer.get("translations") or {}
    return sum(1 for code in ("nl", "fr", "en") if code not in own and not translations.get(code))


def expansion_right(answer: dict, journal_title: str) -> bool:
    """Whether the model's written-out journal name is the curated full name (case, accents and punctuation aside)."""
    full = (answer.get("host") or {}).get("title_full") or ""
    return fuzz.ratio(fold(full), fold(journal_title)) >= 90


# --- the hand-checked key (data/curated/citations/key.csv) ----------------------------------------------------------

def load_key(path: Path) -> dict[str, dict]:
    import csv

    with path.open(encoding="utf-8", newline="") as handle:
        return {row["id"]: row for row in csv.DictReader(handle)}


def answer_of_record(record) -> dict:
    """The parser's fields in the shape of a model answer, so both are scored alike."""
    host = record.host
    return {
        "type": record.type,
        "persons": [{"family": person.family, "given": person.given, "role": person.role} for person in record.persons],
        "title": record.title, "subtitle": record.subtitle, "title_translated": record.title_translated,
        "host": {"title": host.title, "volume": host.volume, "issue": host.issue, "year": host.year, "pages": host.pages} if host else None,
        "publishers": [{"place": record.publisher.place, "name": record.publisher.name}] if record.publisher else [],
        "year": record.year, "extent": record.extent,
        "series": {"title": record.series.title, "number": record.series.number} if record.series else None,
    }


def _alternatives(value: str) -> list[str]:
    return [part.strip() for part in value.split(" || ")]


def _like(value, accepted: str, threshold: int = 90) -> bool:
    folded = fold(str(value or ""))
    return any((fold(alternative) == folded) if not alternative or not folded else fuzz.ratio(folded, fold(alternative)) >= threshold
               for alternative in _alternatives(accepted))


def score_key(answer: dict, row: dict) -> dict[str, bool | None]:
    """Per field against a row of the hand-checked key: right, wrong, or None when not scored. A field the key leaves
    empty is scored only when the answer fills it (a made-up host or publisher counts as wrong); volume, issue and
    first page only for an entry with a host."""
    fields = fields_of_answer(answer)
    host = answer.get("host") or {}
    persons = answer.get("persons") or []
    publishers = answer.get("publishers") or []
    series = answer.get("series") or {}

    def names(role: str) -> list[str]:
        return sorted(fold(person.get("family") or "") for person in persons if person.get("role", "author") == role)

    def optional(name: str, given) -> bool | None:
        accepted = row[name]
        if accepted == "*" or (not accepted and not given):
            return None
        return _like(given, accepted)

    result: dict[str, bool | None] = {
        "type": answer.get("type") in row["type"].split("|"),
        "authors": names("author") == sorted(fold(name) for name in row["authors"].split("; ") if name),
        "editors": names("editor") == sorted(fold(name) for name in row["editors"].split("; ") if name),
        "title": _like(fields["title"], row["title"], 95),
        "title_translated": optional("title_translated", answer.get("title_translated")),
        "host": optional("host", host.get("title")),
        "place": optional("place", next((p.get("place") for p in publishers if p.get("place")), None))
                 if not row["place"] or not publishers else any(_like(p.get("place"), row["place"]) for p in publishers),
        "publisher": optional("publisher", next((p.get("name") for p in publishers if p.get("name")), None))
                     if not row["publisher"] or not publishers else any(_like(p.get("name"), row["publisher"]) for p in publishers),
        "extent": optional("extent", answer.get("extent")),
        "series": optional("series", series.get("title")),
        "series_number": optional("series_number", series.get("number")),
    }
    if row["year"] != "*":
        accepted = {int(year) if year else None for year in _alternatives(row["year"])}
        result["year"] = fields["year"] in accepted
    if row["host"] and row["host"] != "*":
        for name, key, compare in (("volume", "volume", _number), ("issue", "issue", None), ("first_page", "pages", _first_page)):
            accepted = row[key]
            if accepted == "*":
                continue
            given = host.get(key)
            if compare is None:
                result[name] = _like(given, accepted) or any(_number(given) == _number(alt) for alt in _alternatives(accepted) if alt and given)
            else:
                result[name] = any(compare(given) == compare(alt) for alt in _alternatives(accepted))
    return result


# --- prompt v4: parsing only (translations in requests of their own, collected volumes with the full schema) -------

PARSE_VERSION = "4"
PARSE_ENTRY = _object({key: value for key, value in ENTRY["properties"].items()
                       if key not in ("translations", "editions", "contents")}
                      | {"host": _object({key: _NULLABLE_TEXT for key in ("title", "volume", "issue", "year", "pages")}, nullable=True)})
PARSE_SCHEMA = _object({"entries": {"type": "array", "items": PARSE_ENTRY}})

PARSE = """You split entries of the Bibliography of Belgian History (Bibliographie de l'Histoire de Belgique / \
Bibliografie van de Geschiedenis van België, 1952–2017) into fields. Entries are in French, Dutch, German, English \
or Latin, and most were digitised from print with OCR.

You get the section heading, sometimes the entry printed before (context only: do not answer for it), and the \
entries, each after its id in square brackets, sometimes with hints from earlier processing. Answer with one object \
per id, in the same order: never skip, merge or split an entry. Each entry stands alone: never take a value from \
another entry, except the journal or volume that "Ibid." stands for.

What the entry is:
- article: in a journal or newspaper. The journal title follows the article title, is usually abbreviated, and has \
a volume number, a year or an issue ("Biekorf, LXXIV, 1973, 7–8, pp. 202–204").
- chapter: in a collected volume, a Festschrift, an exhibition catalogue or a reference work ("In:", "Dans:", \
"In :", often with the volume's editors, place and publisher; "Flandria Nostra, t. I, Antwerpen, 1957"). A \
contribution to a multi-volume work is a chapter, not an article.
- book: a place followed by a publisher, or a place and a year, then a number of pages ("Bussum, Uitg. P. Brand, \
1955, 210 pp."). Exhibition catalogues, theses and booklets are books. The imprint is never a host.
- journal-issue: a whole issue or volume of a journal; review: a review of a named book; other: none of these.

Fields:
- Copy every value exactly as printed: do not translate, expand abbreviations, modernise spelling or fix OCR \
errors. Journal names stay abbreviated as printed.
- persons are the entry's own authors, editors and translators, printed as "Family (Given)". "(éd.)", "(ed.)", \
"(red.)", "(dir.)", "(uitg.)", "eds." mark editors. "e.a." or "et al." adds no person; "s.n." is no person. The \
editors of the volume a chapter is in ("In: Witte (Els) red. …") belong to that volume, not to the chapter.
- host is the journal or the collected volume: its title, volume, issue, year and pages. A volume title goes in \
host.title without its editors, place or publisher. "Ibid." as journal is the journal of the entry before: put \
that journal's name in host.title, as printed there (a hint may give it).
- publishers: the place and publisher of a book, or of a chapter's volume. A bilingual imprint ("Bruxelles, X; \
Brussel, Y" or "Bruxelles, X — Brussel, Y") gives two. "S.l." is no place, "s.n." no publisher, "s.d." no year.
- year is the year of publication as an integer, also for an article (the year printed with its journal volume; \
"1959–60" gives 1959) and for a chapter (the year of its volume's imprint). In the 1950s volumes a year is often \
printed with two digits after the volume: "Limburg, XXXI, 52, p. 79–80" is volume XXXI of 1952, no issue. null \
when none is printed.
- extent is the whole pagination of a book as printed ("xv–293 p.", "2 vol.", "210 pp.", "s.p."), never the \
format (8°, 4°), the illustrations or the price; an article's or chapter's pages go in host.pages.
- series: a series in parentheses after the imprint, title and number apart ("(Ius romanum medii aevi, V, 5b)": \
title "Ius romanum medii aevi", number "V, 5b").
- title and subtitle as printed; the editors' translation in square brackets after the title goes in \
title_translated, never in title or subtitle (a hint may give it). A bracketed text that only describes the \
subject ("[Izegem]", "[famille luxembourgeoise]", "[Cfr. n° 1234]") is no translation: leave it out or put it in note.
- note: text after " — " or " - " at the end that is no part of the title (a summary, contents, a comment).
- language lists the languages the title (with subtitle) is written in, as ISO 639-1 codes: two only for a title \
printed in two languages. The editors' bracketed translation is not a language of publication.
- ocr_fixes lists only single words that are clearly OCR errors, with the correction ("Seivias" → "Scivias", \
"terrrein" → "terrein"); one or two letters wrong, never a word that may be a historical or regional spelling, \
never an abbreviation. Leave it empty when in doubt.

Five worked examples. Entries:
Section: I. Généralités › C. Travaux d'ensemble
Entry before (context only): Faider-Feytmans (G.). Adolphe Quetelet et les Beaux-Arts. Bull. de l'Ac. R. de B., \
Cl. des Beaux-Arts, 1974, 2, pp. 190–199.

[ex-1] Janssen (C.). Carmelkluis en Carmelwereld. [Ermitage de C. et monde du C.]. Bussum, Uitg. P. Brand, 1955, \
8°, 210 pp., 95 fr. — Esquisse historique de l'Ordre des Frères de N.-D.-du-Mont-Carmel.
    hint: the editors' bracketed translation: Ermitage de C. et monde du C.
[ex-2] Roberts-Jones (Philippe). Madou et Quetelet. Ibid., pp. 200–204.
[ex-3] Dupont (Marie). Les confréries de Huy au XVᵉ siècle. In: Lambert (Jean) & Hoste (Anne) éds. La ville et ses \
métiers. Liège, Éd. du Perron, 1998, pp. 45–67. [Cfr. n° 1234]
[ex-4] Van Damme (Pieter). Het stadhuis van Leuven. Bruxelles, Crédit communal; Brussel, Gemeentekrediet, 1987, \
xii–214 p.
[ex-5] Martin (L.). Les comptes du domaine de Namur (1350–1400). Bruxelles, Palais des Académies, 1975, 8°, 312 p., \
450 fr. (Commission royale d'Histoire, Publications in-octavo, 12).

Answer:
{"entries": [
{"id": "ex-1", "type": "book", "persons": [{"family": "Janssen", "given": "C.", "role": "author"}], "title": \
"Carmelkluis en Carmelwereld", "subtitle": null, "title_translated": "Ermitage de C. et monde du C.", "host": null, \
"publishers": [{"place": "Bussum", "name": "Uitg. P. Brand"}], "year": 1955, "extent": "210 pp.", "series": null, \
"note": "Esquisse historique de l'Ordre des Frères de N.-D.-du-Mont-Carmel.", "language": ["nl"], "ocr_fixes": []},
{"id": "ex-2", "type": "article", "persons": [{"family": "Roberts-Jones", "given": "Philippe", "role": "author"}], \
"title": "Madou et Quetelet", "subtitle": null, "title_translated": null, "host": {"title": "Bull. de l'Ac. R. de \
B., Cl. des Beaux-Arts", "volume": null, "issue": "2", "year": "1974", "pages": "200–204"}, "publishers": [], \
"year": 1974, "extent": null, "series": null, "note": null, "language": ["fr"], "ocr_fixes": []},
{"id": "ex-3", "type": "chapter", "persons": [{"family": "Dupont", "given": "Marie", "role": "author"}], "title": \
"Les confréries de Huy au XVᵉ siècle", "subtitle": null, "title_translated": null, "host": {"title": "La ville et \
ses métiers", "volume": null, "issue": null, "year": "1998", "pages": "45–67"}, "publishers": [{"place": "Liège", \
"name": "Éd. du Perron"}], "year": 1998, "extent": null, "series": null, "note": null, "language": ["fr"], \
"ocr_fixes": []},
{"id": "ex-4", "type": "book", "persons": [{"family": "Van Damme", "given": "Pieter", "role": "author"}], "title": \
"Het stadhuis van Leuven", "subtitle": null, "title_translated": null, "host": null, "publishers": [{"place": \
"Bruxelles", "name": "Crédit communal"}, {"place": "Brussel", "name": "Gemeentekrediet"}], "year": 1987, "extent": \
"xii–214 p.", "series": null, "note": null, "language": ["nl"], "ocr_fixes": []},
{"id": "ex-5", "type": "book", "persons": [{"family": "Martin", "given": "L.", "role": "author"}], "title": "Les \
comptes du domaine de Namur (1350–1400)", "subtitle": null, "title_translated": null, "host": null, "publishers": \
[{"place": "Bruxelles", "name": "Palais des Académies"}], "year": 1975, "extent": "312 p.", "series": {"title": \
"Commission royale d'Histoire, Publications in-octavo", "number": "12"}, "note": null, "language": ["fr"], \
"ocr_fixes": []}]}"""

DRAFT = """

Each entry comes with a draft by a rule-based parser ("draft: …"). Check every field of the draft against the \
printed text: keep what is right, correct what is wrong, fill what is missing. The draft is often wrong on books \
(an imprint read as a journal), on chapters typed as articles, and on years, extents and series."""


def draft_hint(record) -> str:
    """The parser's fields, in one line, for the draft variant."""
    answer = answer_of_record(record)
    parts = [f"type={answer['type']}"]
    if answer["persons"]:
        parts.append("persons=" + ", ".join(f"{p['family']} ({p['given'] or ''}) {p['role']}" for p in answer["persons"]))
    for name in ("title", "subtitle", "title_translated", "year", "extent"):
        if answer.get(name):
            parts.append(f"{name}={answer[name]}")
    if answer["host"]:
        parts.append("host=" + "; ".join(f"{k}={v}" for k, v in answer["host"].items() if v))
    for publisher in answer["publishers"]:
        parts.append(f"publisher={publisher['place'] or ''}: {publisher['name'] or ''}")
    if answer["series"]:
        parts.append(f"series={answer['series']['title']}; number={answer['series']['number'] or ''}")
    return "draft: " + " | ".join(parts)


def checked_ocr_fixes(answer: dict, printed: str, counts=None) -> list[dict]:
    """The model's OCR fixes that pass a rule: one word, printed as such, one or two letters changed, no digits; and,
    given the bibliography's word counts (``bhb.ocr_compare.vocabulary``), a printed word that hardly occurs
    elsewhere (fewer than 3 times) corrected to one that does (3 times or more). The count drops fixes of accents or
    punctuation only and modernised spellings of common words ("Gent" → "Gand"); checked against the Persée reading
    of the 1960s, it raises the share of right fixes from about half to about five in six."""
    from rapidfuzz.distance import Levenshtein

    from bhb.ocr_compare import key

    kept = []
    for fix in answer.get("ocr_fixes") or []:
        wrong, right = (fix.get("printed") or "").strip(), (fix.get("corrected") or "").strip()
        if (wrong and right and wrong != right and " " not in wrong and " " not in right and not re.search(r"\d", wrong + right)
                and re.search(rf"(?<!\w){re.escape(wrong)}(?!\w)", printed) and Levenshtein.distance(wrong, right) <= 2
                and (counts is None or (counts[key(wrong)] - 1 < 3 and counts[key(right)] >= 3))):
            kept.append(fix)
    return kept


def ask_parse(batch: Batch, model: str, cache: Path, reasoning: str | None = None, provider: str | None = None,
              draft: bool = False) -> tuple[dict[str, dict], list[Reply]]:
    """Prompt v4: parsing only, checked per id like ``ask_batch``; a collected volume goes with the full schema (v3)."""
    if len(batch.items) == 1 and is_collected_volume(batch.items[0].printed):
        return ask_batch(batch, model, cache, reasoning, provider)
    system = PARSE + (DRAFT if draft else "")
    reply = call(request_body(system, batch_message(batch), PARSE_SCHEMA, model, reasoning, name="parse", provider=provider), cache)
    replies = [reply]
    entries = (reply.content or {}).get("entries") or []
    if [entry.get("id") for entry in entries] == [item.id for item in batch.items]:
        return {entry["id"]: entry for entry in entries}, replies
    if reply.content is not None:
        reply.error = reply.error or "ids do not match"
    if len(batch.items) == 1 or (reply.error or "").startswith("HTTP 4"):
        return {}, replies
    answers: dict[str, dict] = {}
    before = batch.before
    for item in batch.items:
        single, more = ask_parse(Batch(batch.section, before, [item], batch.markup), model, cache, reasoning, provider, draft)
        answers.update(single)
        replies.extend(more)
        before = item.printed
    return answers, replies


def credit() -> float | None:
    """What is left on the OpenRouter key (None when the key has no limit or the question fails)."""
    try:
        request = urllib.request.Request("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {_key()}"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8")).get("data") or {}
        return data.get("limit_remaining")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


# --- the pass applied to the records (``bhb citations apply``) -----------------------------------------------------

TYPES = {"article", "chapter", "book", "journal-issue", "other"}
# Roles the parser reads that the schema has no word for; the model calls these persons authors.
_PARSER_ROLES = {"compiler", "preface", "illustrator"}


def load_answers(path: Path) -> dict[str, dict]:
    """Record id → the line of a run's ``answers.jsonl`` (model, prompt, answer)."""
    found = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                found[item["id"]] = item
    return found


def load_translations(path: Path) -> dict[str, dict[str, str]]:
    """Record id → its title's translations from a run's ``translations.jsonl``, by language."""
    found = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                found[item["id"]] = {code: item[code].strip() for code in ("nl", "fr", "en") if (item.get(code) or "").strip()}
    return found


def _text(value) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else value


def _imprint(publishers):
    """One imprint from the model's list: a bilingual or shared imprint keeps all its places and names, joined."""
    from collections import Counter

    from bhb.model import Publisher

    places = list(dict.fromkeys(place for p in publishers or [] if (place := _text(p.get("place")))))
    names = list(dict.fromkeys(name for p in publishers or [] if (name := _text(p.get("name")))))
    return Publisher(place="; ".join(places) or None, name="; ".join(names) or None) if places or names else None


# A university press printed after its town, in the bibliography's style ("Amsterdam, University Press"): the
# press is named in full ("Amsterdam University Press"), the place stays. Bare "Univ." is left: it may be the
# university itself.
_UNIVERSITY_PRESS = [
    (re.compile(r"(?:university|univ\.?|u\.)\s*(?:press|pr|p)\.?", re.I), "{place} University Press"),
    (re.compile(r"(?:universitaire|univ\.?)\s*pers\.?", re.I), "Universitaire Pers {place}"),
    (re.compile(r"presses\s+univ(?:ersitaires|\.)?", re.I), "Presses universitaires {de}{place}"),
]

# Presses whose name does not follow "{place} University Press", by the folded place as printed.
_PRESS_NAMES = {
    "toronto": "University of Toronto Press",
    "chicago": "University of Chicago Press",
    "louvain": "Leuven University Press",
    "leuven-louvain": "Leuven University Press",
    "leicester-london": "Leicester University Press",
    "lexington/kentucky": "University Press of Kentucky",
    "brussel": "Brussels University Press",
}


def name_university_press(publisher) -> bool:
    """Name a bare university press after its place, in place; true when it did."""
    if not publisher or not publisher.name or not publisher.place or ";" in publisher.place + publisher.name:
        return False
    place = re.sub(r"\s*\(.*?\)", "", publisher.place).strip(" .,")
    for pattern, form in _UNIVERSITY_PRESS:
        if place and pattern.fullmatch(publisher.name.strip(" .,")):
            de = "d’" if fold(place)[:1] in "aeiouy" else "de "
            english = form.startswith("{place} University")
            publisher.name = (english and _PRESS_NAMES.get(fold(place))) or form.format(place=place, de=de)
            return True
    return False


def apply_answer(record, item: dict, contributors: frozenset[str] = frozenset()) -> None:
    """Write a model answer into its record. The model's fields replace the parser's: on the hand-checked key 97.1 %
    of the fields are right against 84.5 %, and every field filled in from the parser makes it worse (§5c). Kept from
    the parser: the persons where the model gives none (642 entries, nearly all with a printed author), the year
    where the model gives none, the link to the volume's record (``host.id``) with the volume's
    editors and subtitle, a host it found through a cross-reference where the model gives none, and the roles it reads
    that the schema lacks (compiler, preface, illustrator). A collected volume's authors are not its chapters'
    authors (``contributors``); a chapter split from a volume does not take the volume's extent. The printed text and
    the language stay; the model's OCR fixes are not applied to the text (``apply_citations`` keeps them for search)."""
    from bhb.model import Host, Person, Series

    answer = item["answer"]
    flags = record.provenance.flags
    kind = answer.get("type")
    if kind == "review":
        kind = "article" if answer.get("host") else "other"
    if kind in TYPES:
        record.type = kind
    roles = {fold(person.family): person.role for person in record.persons if person.role in _PARSER_ROLES}
    persons = []
    for person in answer.get("persons") or []:
        family = _text(person.get("family"))
        if not family:
            continue
        role = person.get("role") if person.get("role") in ("author", "editor", "translator") else "author"
        role = roles.get(fold(family), role)
        if role == "author" and fold(family) in contributors:
            continue
        found = Person(family=family, given=_text(person.get("given")), role=role)
        if all((fold(other.family), other.given, other.role) != (fold(family), found.given, role) for other in persons):
            persons.append(found)
    if persons or not record.persons:
        record.persons = persons
    record.title = _text(answer.get("title")) or record.title
    record.subtitle = _text(answer.get("subtitle"))
    record.title_translated = _text(answer.get("title_translated"))
    given = {key: _text(value) for key, value in (answer.get("host") or {}).items() if key in ("title", "volume", "issue", "year", "pages")}
    if any(given.values()):
        before = record.host
        record.host = Host(**given)
        if before:
            record.host.id, record.host.editors, record.host.subtitle = before.id, before.editors, before.subtitle
            record.host.publisher = before.publisher
    elif not (record.host and record.host.id):
        record.host = None
    imprint = _imprint(answer.get("publishers"))
    if record.type == "chapter" and record.host:
        record.host.publisher = imprint or record.host.publisher or record.publisher
        record.publisher = None
    elif record.type == "article":
        record.publisher = None
    else:
        record.publisher = imprint
    year = answer.get("year")
    if isinstance(year, int):
        record.year = year
        if "year-from-host" in flags:
            flags.remove("year-from-host")
    elif record.host and re.fullmatch(r"\d{4}", record.host.year or ""):
        record.year = int(record.host.year)
        if "year-from-host" not in flags:
            flags.append("year-from-host")
    record.extent = None if "split-from-contents" in flags else _text(answer.get("extent"))
    series = answer.get("series") or {}
    record.series = Series(title=_text(series.get("title")), number=_text(series.get("number"))) if _text(series.get("title")) else None
    record.note = _text(answer.get("note"))
    record.provenance.parser = f"{item.get('model', '').split('/')[-1]}@v{item.get('prompt', '')}"
    if "parsed-llm" not in flags:
        flags.append("parsed-llm")


def apply_citations(records, answers: dict[str, dict], translations: dict[str, dict[str, str]]) -> dict[str, int]:
    """The citation pass written into the records, and every title's translations (for search only)."""
    from collections import Counter, defaultdict

    counts: Counter[str] = Counter()
    contributors: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if record.host and record.host.id and "split-from-contents" in record.provenance.flags:
            contributors[record.host.id].update(fold(person.family) for person in record.persons if person.role == "author")
    for record in records:
        found = translations.get(record.id)
        record.translations = dict(found) if found else {}
        counts["titles translated"] += bool(found)
        item = answers.get(record.id)
        if item is not None and record.printed:
            before = (record.type, record.title, record.year)
            apply_answer(record, item, frozenset(contributors.get(record.id, ())))
            record.ocr_corrected = [fix["corrected"] for fix in (item.get("answer") or {}).get("ocr_fixes") or []]
            counts["parsed"] += 1
            counts["OCR fixes for search"] += len(record.ocr_corrected)
            counts["type changed"] += record.type != before[0]
            counts["title changed"] += record.title != before[1]
            counts["year changed"] += record.year != before[2]
        counts["university press named"] += name_presses(record)
    counts.update(resync_cited_hosts(records, answers))
    return dict(counts)


def resync_cited_hosts(records, answers: dict[str, dict]) -> dict[str, int]:
    """A chapter linked to its volume through ``Cfr. n°`` (``host-from-cross-ref``) whose own line prints no imprint
    takes its volume's imprint and year as the citation pass parsed them. The build copied the volume's imprint
    before that pass, as the rules had read it: Couttenier's chapter in Vellut, La mémoire du Congo, had "Tervuren"
    as place and "Gent, Musée royal …/ Snoeck" as publisher, and no year (reviewer, 9 Nov 2026). Both stay marked as
    taken from the volume."""
    from collections import Counter

    from bhb.model import Publisher

    by_id = {record.id: record for record in records}
    counts: Counter[str] = Counter()
    for record in records:
        if record.role != "entry" or not record.host or not record.host.id:
            continue
        if "host-from-cross-ref" not in record.provenance.flags:
            continue
        volume = by_id.get(record.host.id)
        if volume is None:
            continue
        item = answers.get(record.id)
        printed_imprint = _imprint(((item or {}).get("answer") or {}).get("publishers")) if item else None
        if not printed_imprint and volume.publisher and (volume.publisher.place or volume.publisher.name):
            fresh = Publisher(volume.publisher.place, volume.publisher.name)
            if record.host.publisher != fresh:
                record.host.publisher = fresh
                counts["imprints taken from the volume"] += 1
        if not record.year and volume.year:
            record.year = int(volume.year)
            if not record.host.year:
                record.host.year = str(volume.year)
            if "year-from-host" not in record.provenance.flags:
                record.provenance.flags.append("year-from-host")
            counts["years taken from the volume"] += 1
    return dict(counts)


def name_presses(record) -> bool:
    """``name_university_press`` on the record's imprint and its volume's, flagged "publisher-named"."""
    named = name_university_press(record.publisher)
    named |= name_university_press(record.host.publisher if record.host else None)
    if named and "publisher-named" not in record.provenance.flags:
        record.provenance.flags.append("publisher-named")
    return named
