// Words the search index adds to a record, so that a search can be narrowed to its places or its journal: a tag and
// ten digits made from the id (two FNV-1a hashes), shared by the index build (scripts/build-index.mjs) and the page.
// They replace Pagefind filters, whose every value Pagefind counts on every search: the thousands of places and
// journals, whose counts the page never shows, made each search seconds slower (7 Nov 2026). All of one length,
// since a word also finds the longer words it begins with; digits only, so the check for unknown words skips them.

function fnv(text, seed) {
  let hash = seed >>> 0;
  for (const char of text) {
    hash ^= char.codePointAt(0);
    hash = Math.imul(hash, 16777619) >>> 0;
  }
  return hash;
}

/** The index word for a place (tag "pl") or a journal (tag "jn") id, e.g. keyWord("pl", "nis:44021"). */
export function keyWord(tag, key) {
  const one = String(fnv(key, 2166136261) % 100000).padStart(5, "0");
  const two = String(fnv(key, 2654435761) % 100000).padStart(5, "0");
  return `${tag}_${one}${two}`;
}

/** A person as the author row shows it, "Family (Given)", folded: the key of ``personWord``. */
export function personKey(family, given) {
  const norm = (text) => String(text || "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
  return `${norm(family)}|${norm(given)}`;
}

/**
 * A person as one index word (tag "pn"), so that a search for a name, "Bertrand (Paul)", finds that person, and not
 * an entry whose Paul and whose Bertrand are two people (Sébastien, 9 Nov 2026).
 */
export function personWord(family, given) {
  return keyWord("pn", personKey(family, given));
}

/** "Family (Given)" → [family, given], as an author link writes a name; null for any other query. */
export function personName(text) {
  const match = String(text || "").trim().match(/^([^()]+?)\s*\(([^()]+)\)$/);
  return match ? [match[1], match[2]] : null;
}
