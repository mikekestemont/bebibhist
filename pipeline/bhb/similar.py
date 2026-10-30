"""Similar publications: one sentence embedding per entry, and its nearest neighbours.

The text is the title, the subtitle and the translated title. Authors and the host are left out, so
that neighbours share a subject rather than a person or a journal. Vectors are cached per record and
text, so a rebuild only encodes what changed. The idea and set-up follow Enrique Manjavacas's BNTL
search engine (https://github.com/emanjavacas/bntl); the neighbours here are precomputed for a
static site.
"""

from __future__ import annotations

import hashlib
import heapq
import random
import time
from operator import itemgetter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bhb.model import Record
from bhb.textutil import fold, squash

DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_K = 10
MIN_TOKENS = 2

# e5 models expect a prefix; "query: " is the one for symmetric similarity.
_PREFIX = {
    "intfloat/multilingual-e5-small": "query: ",
    "intfloat/multilingual-e5-base": "query: ",
    "intfloat/multilingual-e5-large": "query: ",
}
_MAX_TOKENS = 128

_FRENCH = frozenset("le la les des du et aux au sur dans une un pour par".split())
_DUTCH = frozenset("het een van en op voor naar uit bij met over tot".split())

# Hybrid score: the embedding cosine plus LEXICAL_WEIGHT times a TF-IDF cosine of the titles over rare
# words only (in at most RARE_TITLES titles). The embedding finds the same subject across languages; the
# TF-IDF part rewards shared rare words, in practice names (Guibert, Gembloux), which the embedding weighs
# too lightly. Common words are left out because they tie a title to others in its own language.
LEXICAL_WEIGHT = 0.1
RARE_TITLES = 50
_SHORT_WORDS = _FRENCH | _DUTCH | frozenset("the and with from into dans sous entre zijn door naar onder tegen".split())


def embed_text(record: Record) -> str | None:
    """Title, subtitle and translated title, or None for records that get no neighbours."""
    if record.role != "entry" or record.is_cross_listing:
        return None
    parts = [squash(part).rstrip(" .") for part in (record.title, record.subtitle, record.title_translated) if part]
    text = ". ".join(part for part in parts if part)
    if len(fold(text).split()) < MIN_TOKENS:
        return None
    return text


def same_work_key(text: str) -> str:
    """Two records with the same folded text are the same work, or say nothing about each other."""
    return fold(text)


@dataclass
class Vectors:
    ids: list[str]
    texts: list[str]
    matrix: np.ndarray  # float32, L2-normalised, one row per id


def encode(
    records: list[Record],
    model_name: str = DEFAULT_MODEL,
    cache: Path | None = None,
    batch_size: int = 128,
    log=print,
) -> Vectors:
    pairs = [(record.id, text) for record in records if (text := embed_text(record))]
    ids = [record_id for record_id, _ in pairs]
    texts = [text for _, text in pairs]
    digests = [_digest(model_name, text) for text in texts]
    cached = _load_cache(cache) if cache else {}
    missing = [index for index, digest in enumerate(digests) if digest not in cached]
    log(f"similar: {len(texts)} texts, {len(texts) - len(missing)} cached, {len(missing)} to encode with {model_name}")
    if missing:
        from sentence_transformers import SentenceTransformer

        started = time.time()
        model = SentenceTransformer(model_name, device=_device())
        model.max_seq_length = min(model.max_seq_length or _MAX_TOKENS, _MAX_TOKENS)
        prefix = _PREFIX.get(model_name, "")
        fresh = model.encode(
            [prefix + texts[index] for index in missing],
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=True,
        ).astype(np.float16)
        for index, vector in zip(missing, fresh):
            cached[digests[index]] = vector
        log(f"similar: encoded {len(missing)} texts in {time.time() - started:.0f} s")
        if cache:
            _save_cache(cache, cached)
    matrix = np.stack([cached[digest] for digest in digests]).astype(np.float32) if digests else np.zeros((0, 0), np.float32)
    return Vectors(ids, texts, matrix)


def neighbours(vectors: Vectors, k: int = DEFAULT_K, chunk: int = 1024) -> dict[str, list[tuple[str, float]]]:
    """Top-k neighbours by the hybrid score, without the record itself and without records of the same text.

    Candidates are the best by embedding and the best by TF-IDF, so three titles on Guibert of Gembloux
    find each other although the embedding alone puts other subjects closer.
    """
    keys = [same_work_key(text) for text in vectors.texts]
    matrix = vectors.matrix
    total = matrix.shape[0]
    wanted = min(total - 1, k * 5)
    found: dict[str, list[tuple[str, float]]] = {}
    if wanted <= 0:
        return found
    lexical = _tfidf(vectors.texts)
    for start, columns, values in _top_candidates(matrix, wanted, chunk):
        words = (lexical[start : start + columns.shape[0]] @ lexical.T).tocsr()
        for row in range(columns.shape[0]):
            source = start + row
            low, high = words.indptr[row], words.indptr[row + 1]
            shared = dict(zip(words.indices[low:high].tolist(), words.data[low:high].tolist()))
            shared.pop(source, None)
            cosine = dict(zip(columns[row].tolist(), values[row].tolist()))
            extra = [column for column, _ in heapq.nlargest(k * 2, shared.items(), key=itemgetter(1)) if column not in cosine]
            if extra:
                cosine.update(zip(extra, (matrix[extra] @ matrix[source]).tolist()))
            scored = sorted(
                ((score + LEXICAL_WEIGHT * shared.get(column, 0.0), column) for column, score in cosine.items()),
                reverse=True,
            )
            kept: list[tuple[str, float]] = []
            seen = {keys[source]}
            for score, column in scored:
                if keys[column] in seen:
                    continue
                seen.add(keys[column])
                kept.append((vectors.ids[column], round(score, 4)))
                if len(kept) == k:
                    break
            found[vectors.ids[source]] = kept
    return found


def _tfidf(texts: list[str]):
    """Rows are L2-normalised TF-IDF vectors of the folded titles, over words in 2 to RARE_TITLES titles."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(
        preprocessor=fold,
        token_pattern=r"(?u)\b[a-z]{3,}\b",
        stop_words=sorted(_SHORT_WORDS),
        sublinear_tf=True,
        min_df=2,
        max_df=RARE_TITLES,
        dtype=np.float32,
    )
    return vectorizer.fit_transform(texts).tocsr()


def _top_candidates(matrix: np.ndarray, wanted: int, chunk: int):
    """Yield (start, columns, scores) per block of rows, best first, without each row itself.

    On a machine with torch the top-k runs on the GPU; numpy's argpartition is single-threaded and
    took about 5 minutes for the whole corpus.
    """
    try:
        import torch
    except ImportError:
        torch = None
    if torch is not None:
        device = _device()
        full = torch.from_numpy(matrix).to(device)
        for start in range(0, matrix.shape[0], chunk):
            scores = full[start : start + chunk] @ full.T
            rows = torch.arange(scores.shape[0], device=device)
            scores[rows, rows + start] = -torch.inf
            values, columns = torch.topk(scores, wanted, dim=1)
            yield start, columns.cpu().numpy(), values.cpu().numpy()
        return
    for start in range(0, matrix.shape[0], chunk):
        scores = matrix[start : start + chunk] @ matrix.T
        rows = np.arange(scores.shape[0])
        scores[rows, rows + start] = -np.inf
        candidates = np.argpartition(-scores, wanted, axis=1)[:, :wanted]
        order = np.argsort(-np.take_along_axis(scores, candidates, axis=1), axis=1)
        columns = np.take_along_axis(candidates, order, axis=1)
        yield start, columns, np.take_along_axis(scores, columns, axis=1)


def apply(records: list[Record], found: dict[str, list[tuple[str, float]]]) -> int:
    count = 0
    for record in records:
        pairs = found.get(record.id, [])
        record.similar = [record_id for record_id, _ in pairs]
        record.similar_scores = [score for _, score in pairs]
        count += bool(pairs)
    return count


def language_of(text: str) -> str | None:
    """French or Dutch from function words; None when unclear or when the title gives both."""
    words = fold(text).split()
    french = sum(word in _FRENCH for word in words)
    dutch = sum(word in _DUTCH for word in words)
    if french and dutch:
        return None
    if french:
        return "fr"
    if dutch:
        return "nl"
    return None


def checked_code(record: Record) -> str | None:
    """The record's own classification, when a person or the printed volume set it."""
    for category in record.categories:
        if category.code and not category.machine:
            return category.code
    return record.bhb_codes[0] if record.bhb_codes else None


def quality(records: list[Record], found: dict[str, list[tuple[str, float]]]) -> dict[str, float]:
    """How often a neighbour shares the record's checked code (two and three levels deep), and how often
    it is in the other language. Codes are a rough proxy for subject: a good neighbour can sit under
    another heading."""
    by_id = {record.id: record for record in records}
    same2 = same3 = coded = 0
    crossed = paired = 0
    for record_id, pairs in found.items():
        source = by_id[record_id]
        code = checked_code(source)
        language = language_of(embed_text(source) or "")
        for other_id, _ in pairs:
            other = by_id[other_id]
            other_code = checked_code(other)
            if code and other_code:
                coded += 1
                same2 += _prefix(code, 2) == _prefix(other_code, 2)
                same3 += _prefix(code, 3) == _prefix(other_code, 3)
            other_language = language_of(embed_text(other) or "")
            if language and other_language:
                paired += 1
                crossed += language != other_language
    return {
        "same_period": same2 / coded if coded else 0.0,
        "same_section": same3 / coded if coded else 0.0,
        "coded_pairs": coded,
        "other_language": crossed / paired if paired else 0.0,
        "language_pairs": paired,
    }


def _prefix(code: str, depth: int) -> str:
    return ".".join(code.strip(".").split(".")[:depth])


def write_report(path: Path, records: list[Record], vectors: Vectors, found: dict, model_name: str, sample: int = 30, seed: int = 7) -> None:
    by_id = {record.id: record for record in records}
    firsts = np.array([pairs[0][1] for pairs in found.values() if pairs]) if found else np.zeros(0)
    tenths = np.array([pairs[-1][1] for pairs in found.values() if pairs]) if found else np.zeros(0)
    lines = [
        "# Similar publications",
        "",
        f"Model: `{model_name}`. Text: title, subtitle, translated title. Entries with neighbours: {len(found)}.",
        "No cosine floor yet: every record keeps its top neighbours, so the floor can be set from this check.",
        "",
        "| Cosine | 1st neighbour | last neighbour |",
        "|---|---:|---:|",
    ]
    for q in (0.1, 0.25, 0.5, 0.75, 0.9):
        lines.append(f"| p{int(q * 100)} | {np.quantile(firsts, q):.3f} | {np.quantile(tenths, q):.3f} |" if len(firsts) else f"| p{int(q * 100)} | – | – |")
    scores = quality(records, found)
    lines += [
        "",
        f"Neighbours with the same checked code, two levels deep (e.g. III.D): **{scores['same_period']:.1%}**; "
        f"three levels deep (e.g. III.D.2): **{scores['same_section']:.1%}** ({scores['coded_pairs']} pairs).",
        f"Neighbours in the other language (French/Dutch, from function words): **{scores['other_language']:.1%}** "
        f"({scores['language_pairs']} pairs).",
    ]
    lines += ["", f"## {sample} random records", ""]
    rng = random.Random(seed)
    for record_id in rng.sample(sorted(found), min(sample, len(found))):
        source = by_id[record_id]
        lines.append(f"**{record_id}** ({source.bgb_year}) {embed_text(source)}")
        lines.append("")
        for other_id, score in found[record_id]:
            other = by_id[other_id]
            lines.append(f"- {score:.3f} `{other_id}` ({other.bgb_year}) {embed_text(other)}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _device() -> str:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _digest(model_name: str, text: str) -> str:
    return hashlib.sha1(f"{model_name}\n{text}".encode("utf-8")).hexdigest()


def _load_cache(path: Path) -> dict[str, np.ndarray]:
    if not path.is_file():
        return {}
    data = np.load(path)
    return dict(zip(data["digests"].tolist(), data["vectors"]))


def _save_cache(path: Path, cached: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    digests = sorted(cached)
    np.savez(path, digests=np.array(digests), vectors=np.stack([cached[digest] for digest in digests]))
