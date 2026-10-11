"""Plain-text parser for a printed BGB citation.

The printed line is the authority. Tags, when the vendor supplied them, are
applied elsewhere; this module is what PDF years and untagged citations use.

Shape it expects, with many local variations:

    Surname (Given), Surname (Given) & Surname (Given). Title. [Translation].
    Host, VOLUME, year, issue, pp. X-Y. — Annotation.

    Surname (Given). Title. Place, Publisher, year, 8°, 158 p. (Series, 12).

    Surname (Given). Title. In: Editor (A.). Host title. Place, Publisher, year, pp. X-Y.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bhb.textutil import squash

_CROSS = re.compile(
    r"\[?\s*(?:cfr|voir|zie)\.?\s+n(?:°|º|o|r)\.?\s*"
    r"((?:\d{2,6}(?:\s*(?:bis|ter|quater))?(?:\s*[,;]\s*|\s+(?:et|en|and)\s+)?)+)\s*\]?",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<!\d)((?:1[5-9]|20)\d{2})(?!\d)")
_PERSON = re.compile(r"^([A-ZÀ-Ý][^().]{0,80}?)\s*\(\s*([^)]{1,60})\s*\)")
_EDITOR = re.compile(r"^\s*\((?:éds?|eds?|réd|red|dir|édit)\.?\)", re.IGNORECASE)
_EDITOR_BARE = re.compile(r"^\s+(?:dir|éd|ed|red)\.(?=\s|$)", re.IGNORECASE)
_ETAL = re.compile(r"^(?:e\.\s*a\.|e\.a\.|et\s+al\.)", re.IGNORECASE)
_MMV = re.compile(
    r"^(?:m\.m\.v\.|avec la collaboration de|met medewerking van)\s+",
    re.IGNORECASE,
)
_SEP = re.compile(r"^(?:,\s*|&\s*|et\s+|en\s+)")
_ROLE_WORD = re.compile(r"^(?:éds?|eds?|réd|red|dir|édit)\.?$", re.IGNORECASE)
_ABBREV = {
    "rev", "vol", "nr", "n", "dr", "mr", "mgr", "prof", "cf", "cfr", "ed", "éd",
    "dir", "red", "ill", "fig", "pl", "t", "tom", "fasc", "jg", "s", "l", "d",
    "etc", "sq", "suppl", "ms", "mss", "p", "pp", "no", "nos", "op", "cit",
    "ibid", "id", "al", "b", "hist", "philol", "gesch", "ts", "bull", "ann",
}
_IN = re.compile(r"\bIn\s*:\s*", re.IGNORECASE)
_PAGES = re.compile(
    r"(?:(?:,|\.)\s*)((?:pp?\.)\s*\d[\d\s;,\-–.p]*)\s*$",
    re.IGNORECASE,
)
_EXTENT = re.compile(
    r"(?:,\s*)((?:\d+|[ivxlcdmIVXLCDM]+)\s*p\.?|SP)\s*$",
    re.IGNORECASE,
)
_PRICE = re.compile(r"(?:,\s*)(\d+\s*(?:F\.?\s*B\.?|FB|€))\s*$", re.IGNORECASE)
_FORMAT = re.compile(r"(?:,\s*)(8°|in-8°?|in-4°?|ill\.|fig\.|pl\.|cartes)\s*$", re.IGNORECASE)
_VOLUME = re.compile(r",\s*([IVXLCDM]{1,8}|\d{1,3}(?:\s*[-–/]\s*\d{1,3})?)\s*$")
_ISSUE = re.compile(r"^\d{1,4}(?:\s*[-–/]\s*\d{1,4})?$")
_SERIES_SPLIT = re.compile(r"(.+?)\s*[,:]\s*(\d+)\s*$")
_SERIES_NUM = re.compile(r"(.+?)\s+(\d+)\s*$")


@dataclass
class ParsedCitation:
    type: str = "other"
    title: str | None = None
    title_translated: str | None = None
    persons: list[dict[str, str | None]] = field(default_factory=list)
    host_title: str | None = None
    volume: str | None = None
    issue: str | None = None
    year: int | None = None
    pages: str | None = None
    place: str | None = None
    publisher: str | None = None
    extent: str | None = None
    series_title: str | None = None
    series_number: str | None = None
    note: str | None = None
    cross_refs: list[tuple[int | None, str]] = field(default_factory=list)
    is_cross_listing: bool = False
    flags: list[str] = field(default_factory=list)
    confidence: float = 0.0


def cross_references(text: str) -> tuple[str, list[tuple[int | None, str]]]:
    """Remove ``Cfr.`` / ``Voir`` / ``Zie`` pointers. Returns the cleaned text and ``(year, number)`` pairs."""
    return _cross_refs(text)


def parse_citation(text: str) -> ParsedCitation:
    parsed = ParsedCitation()
    original = squash(text)
    if not original:
        parsed.flags.append("empty")
        parsed.confidence = 0.05
        return parsed

    without_refs, parsed.cross_refs = _cross_refs(original)
    letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", without_refs)
    if parsed.cross_refs and len(letters) < 12:
        parsed.is_cross_listing = True
        parsed.type = "other"
        parsed.confidence = 0.9
        return parsed

    note, body = _split_annotation(without_refs)
    body = _mask_unknowns(body, parsed.flags)
    notes: list[str] = []
    if note:
        notes.append(note)

    body, trailing = _take_trailing_brackets(body)
    if trailing:
        notes.append(trailing)

    persons, body, author_flags, editors = _split_authors(body)
    parsed.persons = persons
    parsed.flags.extend(author_flags)
    if editors:
        for person in parsed.persons:
            person["role"] = "editor"

    translated, body = _take_translation(body)
    parsed.title_translated = translated

    if match := _IN.search(body):
        parsed.type = "chapter"
        parsed.title = _tidy(body[: match.start()])
        _parse_host_target(body[match.end() :], parsed)
    else:
        _parse_imprint(body, parsed)

    if notes:
        parsed.note = _tidy(" ".join(notes))
    _blank_unknowns(parsed)
    if parsed.host_title and parsed.host_title.lower().startswith("ibid"):
        parsed.flags.append("ibid-host")
    parsed.confidence = _confidence(parsed)
    return parsed


def _cross_refs(text: str) -> tuple[str, list[tuple[int | None, str]]]:
    found: list[tuple[int | None, str]] = []

    def repl(match: re.Match[str]) -> str:
        for number in re.findall(r"\d{2,6}(?:bis|ter|quater)?", match.group(1), flags=re.IGNORECASE):
            found.append((None, number.lower() if number[-1:].isalpha() else number))
        return " "
    return squash(_CROSS.sub(repl, text)), found


def _split_annotation(text: str) -> tuple[str | None, str]:
    """An em dash after the pages or the extent introduces the annotation.

    An em dash earlier in the line is a parallel title and stays in the title.
    """
    for match in re.finditer(r"\s[—–]\s", text):
        left = text[: match.start()].rstrip()
        if re.search(r"p{1,2}\.\s*\d|\d+\s*p\.", left, re.IGNORECASE):
            return text[match.end() :].strip(" ."), left
    return None, text


def _take_trailing_brackets(text: str) -> tuple[str, str | None]:
    match = re.search(r"\s*\[([^\[\]]{2,200})\]\s*$", text)
    if not match:
        return text, None
    return text[: match.start()].rstrip(" ."), match.group(1).strip()


def _take_translation(text: str) -> tuple[str | None, str]:
    match = re.search(r"\[([^\[\]]{8,300})\]", text)
    if not match:
        return None, text
    inner = match.group(1).strip()
    if len(inner.split()) < 3 and not inner[:1].isupper():
        return None, text
    rest = squash(text[: match.start()] + " " + text[match.end() :])
    return inner, rest


def _split_authors(text: str) -> tuple[list[dict[str, str | None]], str, list[str], bool]:
    persons: list[dict[str, str | None]] = []
    flags: list[str] = []
    editors = False
    rest = text
    while True:
        rest = rest.lstrip()
        if persons:
            if match := _ETAL.match(rest):
                flags.append("et-al")
                rest = rest[match.end() :]
                break
            if match := _MMV.match(rest):
                flags.append("collaboration")
                rest = rest[match.end() :]
            elif match := _SEP.match(rest):
                rest = rest[match.end() :]
            else:
                break
        match = _PERSON.match(rest.lstrip())
        if not match:
            break
        family = squash(match.group(1)).strip(" ,")
        given = squash(match.group(2))
        if len(family.split()) > 8:
            break
        rest = rest.lstrip()[match.end() :]
        role = "author"
        if _ROLE_WORD.match(given):
            role = "editor"
            editors = True
            given = None
        if marker := _EDITOR.match(rest) or _EDITOR_BARE.match(rest):
            editors = True
            role = "editor"
            rest = rest[marker.end() :]
        persons.append({"family": family, "given": given, "role": role})
    if not persons:
        return [], text, flags, False
    rest = rest.lstrip()
    if marker := _EDITOR.match(rest) or _EDITOR_BARE.match(rest):
        editors = True
        rest = rest[marker.end() :].lstrip()
    if rest.startswith("."):
        rest = rest[1:].lstrip()
    return persons, rest, flags, editors


def _parse_host_target(target: str, parsed: ParsedCitation) -> None:
    """The part after ``In:``. A leading ``Name (Init.)`` is the host's editor, not the entry's author."""
    _editors, rest, _flags, _mark = _split_authors(target)
    _parse_imprint(rest or target, parsed)
    parsed.type = "chapter"


def _parse_imprint(body: str, parsed: ParsedCitation) -> None:
    series_raw, body = _peel_series(body)
    if series_raw and parsed.series_title is None:
        parsed.series_title, parsed.series_number = _split_series(series_raw)
    body, extras = _strip_tail(body)
    parsed.pages = extras.get("pages")
    parsed.extent = extras.get("extent")
    if extras.get("multi"):
        parsed.flags.append("multi-range")
    year, before, after = _peel_year(body)
    parsed.year = year
    if after and _ISSUE.match(after):
        parsed.issue = after
    elif after and re.search(r"série|serie|reeks", after, re.IGNORECASE):
        parsed.series_title = parsed.series_title or after
    title_was_preset = parsed.title is not None
    # A chapter in a book ends with pages but its imprint is still Place, Publisher.
    if parsed.extent or _looks_like_book_imprint(before):
        title, place, publisher = _split_place_publisher(before)
        parsed.place = place
        parsed.publisher = publisher
        if parsed.type == "chapter" or title_was_preset:
            parsed.host_title = title
        else:
            parsed.title = title
            parsed.type = "book"
        return
    if parsed.pages:
        volume, left = _peel_volume(before)
        parsed.volume = volume
        title, host = _split_title_host(left)
        if title_was_preset:
            parsed.host_title = host or title
        else:
            parsed.title = title
            parsed.host_title = host
            parsed.type = "article"
        return
    volume, left = _peel_volume(before)
    if volume and year:
        title, host = _split_title_host(left)
        if not title_was_preset:
            parsed.title = title
        parsed.host_title = host
        parsed.volume = volume
        if parsed.type != "chapter":
            parsed.type = "article"
        return
    if not title_was_preset:
        parsed.title = _tidy(before) or None
    if parsed.type != "chapter":
        parsed.type = "other"


def _peel_series(text: str) -> tuple[str | None, str]:
    match = re.search(r"\s*\(([^()]{3,180})\)\s*\.?\s*$", text)
    if not match:
        return None, text
    inner = match.group(1).strip()
    if re.match(r"(?:éd|ed|dir|red)\.?$", inner, re.IGNORECASE):
        return None, text
    return inner, text[: match.start()].rstrip(" .")


def _split_series(inner: str) -> tuple[str | None, str | None]:
    if match := _SERIES_SPLIT.match(inner):
        return _tidy(match.group(1)), match.group(2)
    if match := _SERIES_NUM.match(inner):
        return _tidy(match.group(1)), match.group(2)
    return _tidy(inner), None


def _strip_tail(text: str) -> tuple[str, dict[str, str]]:
    info: dict[str, str] = {}
    value = text.strip()
    changed = True
    while changed:
        changed = False
        for pattern in (_PRICE, _FORMAT):
            if match := pattern.search(value):
                value = value[: match.start()].rstrip(" ,.")
                changed = True
                break
        if changed:
            continue
        if "extent" not in info and (match := _EXTENT.search(value)):
            extent = match.group(1).strip(" .")
            info["extent"] = "s.p." if extent == "SP" else extent
            if not info["extent"].endswith(".") and info["extent"].endswith("p"):
                info["extent"] += "."
            value = value[: match.start()].rstrip(" ,.")
            changed = True
            continue
        if "pages" not in info and (match := _PAGES.search(value)):
            info["pages"] = _clean_pages(match.group(1))
            if ";" in info["pages"]:
                info["multi"] = "1"
            value = value[: match.start()].rstrip(" ,.")
            changed = True
    return value, info


def _clean_pages(clause: str) -> str:
    clause = re.sub(r"^p{1,2}\.\s*", "", clause.strip(), count=1, flags=re.IGNORECASE)
    return clause.strip(" .")


def _peel_year(text: str) -> tuple[int | None, str, str]:
    matches = list(_YEAR.finditer(text))
    if not matches:
        return None, text, ""
    match = matches[-1]
    before = text[: match.start()].rstrip(" ,.")
    after = text[match.end() :].strip(" ,.")
    return int(match.group(1)), before, after


def _peel_volume(text: str) -> tuple[str | None, str]:
    match = _VOLUME.search(text)
    if not match:
        return None, text
    return match.group(1).replace(" ", ""), text[: match.start()].rstrip(" ,")


def _split_title_host(text: str) -> tuple[str | None, str | None]:
    candidates = []
    for match in re.finditer(r"\.\s+", text):
        word = re.split(r"\s+", text[: match.start()])[-1].strip("([,'«").lower().rstrip(".")
        if word in _ABBREV or (len(word) <= 2 and word.isalpha()):
            continue
        candidates.append(match.end())
    if not candidates:
        tidy = _tidy(text)
        return (tidy or None), None
    cut = candidates[-1]
    return _tidy(text[: cut]) or None, _tidy(text[cut:]) or None


def _looks_like_book_imprint(text: str) -> bool:
    match = re.search(r"\.\s+([^.]{2,60}),\s*([^.]{2,80})$", text)
    if not match:
        return False
    publisher = match.group(2).strip()
    if re.fullmatch(r"[IVXLCDM]{1,8}|\d{1,3}(?:\s*[-–/]\s*\d{1,3})?", publisher):
        return False
    return True


def _mask_unknowns(text: str, flags: list[str]) -> str:
    """``s.l.`` / ``s.n.`` / ``s.d.`` / ``s.p.`` contain periods that break imprint splitting."""
    # The letter before the period must not be inside a word ("fonds. Les", "parcours. pp.").
    replacements = (
        (r"(?<![A-Za-zÀ-ÿ])s\.\s*l\.(?![A-Za-zÀ-ÿ])", "SL", "s.l."),
        (r"(?<![A-Za-zÀ-ÿ])s\.\s*n\.(?![A-Za-zÀ-ÿ])", "SN", "s.n."),
        (r"(?<![A-Za-zÀ-ÿ])s\.\s*d\.(?![A-Za-zÀ-ÿ])", "SD", "s.d."),
        (r"(?<![A-Za-zÀ-ÿ])s\.\s*p\.(?![A-Za-zÀ-ÿ])", "SP", "s.p."),
    )
    for pattern, token, flag in replacements:
        if re.search(pattern, text, flags=re.IGNORECASE):
            flags.append(flag)
            text = re.sub(pattern, token, text, flags=re.IGNORECASE)
    text = re.sub(r",?\s*\bSD\b", "", text)
    return squash(text)


def _split_place_publisher(text: str) -> tuple[str | None, str | None, str | None]:
    both = re.search(r"\.\s+([^.]{2,60}),\s*([^.]{2,80})$", text)
    if both:
        return _tidy(text[: both.start()]), both.group(1).strip(), both.group(2).strip()
    place_only = re.search(r"\.\s+([^.]{2,60})$", text)
    if place_only:
        return _tidy(text[: place_only.start()]), place_only.group(1).strip(), None
    return _tidy(text), None, None


def _blank_unknowns(parsed: ParsedCitation) -> None:
    if parsed.place in {"SL", "s.l.", "s. l."}:
        parsed.place = None
    if parsed.publisher in {"SN", "s.n.", "s. n."}:
        parsed.publisher = None
    if parsed.title:
        parsed.title = re.sub(r"\b(?:SL|SN|SD|SP)\b", "", parsed.title).strip(" ,.")
        parsed.title = parsed.title or None


def _tidy(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = squash(text).strip(" .;,-")
    return cleaned or None


def _confidence(parsed: ParsedCitation) -> float:
    score = 0.35
    if parsed.title:
        score += 0.2
    if parsed.persons:
        score += 0.15
    if parsed.year:
        score += 0.1
    if parsed.type in {"article", "chapter"} and parsed.host_title:
        score += 0.1
    if parsed.type == "book" and (parsed.place or parsed.publisher):
        score += 0.1
    if parsed.pages or parsed.extent:
        score += 0.1
    if parsed.type == "other":
        score -= 0.05
    score -= 0.04 * len(parsed.flags)
    return round(max(0.05, min(0.98, score)), 2)
