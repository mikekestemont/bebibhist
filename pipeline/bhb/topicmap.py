"""The topic map: every entry as a point on a map of subjects, with named regions at three levels.

Layout. Each title's English machine translation (the title itself when it has none) is embedded with bge-m3,
from the vectors ``bhb similar`` caches; each language's mean vector is taken out, so that Dutch and French titles
on one subject meet; UMAP places the vectors in two dimensions, lightly guided by the entry's first subject area
(target weight 0.1). Of the layouts measured on 7 Nov 2026 this mixed the languages best (a Dutch title's 15
nearest neighbours on the map are 56 % Dutch, against 49 % of all titles; French 46 % against 37 %), while the
subject areas formed broad regions without squeezing the small islands of specific subjects. Unguided, the map
did not split by subject (29 % of neighbours share it, against 62 % guided); guided at weight 0.2 without the
centring, it split by language more and its islands shrank.

Regions. The map is cut into cells by k-means on the positions, so that every part of it has a name (density
clustering left two thirds of the titles outside any region); the cells are grouped into larger regions by
k-means on their centres, weighted by size: three nested levels of about 24, 120 and 600 regions.

Names. A local model (Mistral Small 3.2, 4-bit, through mlx-lm) names each region in Dutch, French and English: a
cell from a sample of its titles and its most distinctive words, a larger region from the names of its parts and
a sample of titles. Every answer is cached by its prompt, so a rerun only asks what changed.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bhb.model import Record
from bhb.similar import embed_text
from bhb.textutil import fold, squash

LEVELS = (24, 120, 600)
TARGET_WEIGHT = 0.1
SEED = 7
THEMES = ("local", "political", "economic", "social", "religious", "cultural", "reference", "general")
MODEL = "mlx-community/Mistral-Small-3.2-24B-Instruct-2506-4bit"
REVISION = "2a1d5eabfc504747bdc24178394821a1efc0edde"
# Titles shown to the model per region: the ones nearest its centre, then a random sample of the rest.
CENTRAL_TITLES = 12
SAMPLED_TITLES = 18

_STOP = frozenset(
    """a an and the of in on at to for from by with into about between during under over its their his her
    as or is are was were be been some new two three first second study studies history historical notes note
    contribution contributions remarks aspects problem problems case century centuries belgium belgian
    """.split()
)


def layout_text(record: Record) -> str | None:
    """The text a title is placed by: its English machine translation, or the title when it has none."""
    own = embed_text(record)
    if not own:
        return None
    return squash(record.translations.get("en") or "").rstrip(" .") or own


def first_language(record: Record) -> str:
    return (record.language_suggested or ["?"])[0]


def first_theme(record: Record) -> int:
    """The index of the entry's first subject area in ``THEMES``, or -1 (UMAP's "unlabelled")."""
    for theme in record.theme:
        if theme in THEMES:
            return THEMES.index(theme)
    return -1


def centred(matrix: np.ndarray, languages: list[str], minimum: int = 200) -> np.ndarray:
    """The vectors with each language's mean taken out, normalised again; rare languages are left as they are."""
    out = matrix.astype(np.float32).copy()
    codes = np.array(languages)
    for language in set(languages):
        rows = codes == language
        if rows.sum() >= minimum:
            out[rows] -= out[rows].mean(axis=0)
    out /= np.linalg.norm(out, axis=1, keepdims=True) + 1e-9
    return out


def unit_square(xy: np.ndarray, keep: float = 0.998) -> np.ndarray:
    """Positions scaled into [0, 1] by the central ``keep`` share of the points; the far outliers sit on the edge."""
    tail = (1 - keep) / 2 * 100
    low, high = np.percentile(xy, tail, axis=0), np.percentile(xy, 100 - tail, axis=0)
    span = float(max(high - low))
    centre = (low + high) / 2
    return np.clip((xy - centre) / span + 0.5, 0.0, 1.0).astype(np.float32)


def layout(records: list[Record], cache: Path, log=print) -> tuple[list[str], np.ndarray]:
    """The ids of the placed entries and their positions in the unit square."""
    import umap

    from bhb.similar import encode

    vectors = encode(records, cache=cache, text_of=layout_text, log=log)
    by_id = {record.id: record for record in records}
    placed = [by_id[record_id] for record_id in vectors.ids]
    matrix = centred(vectors.matrix, [first_language(record) for record in placed])
    labels = np.array([first_theme(record) for record in placed])
    log(f"topicmap: UMAP of {len(placed)} titles")
    model = umap.UMAP(
        n_neighbors=50, min_dist=0.1, metric="cosine", low_memory=True, target_weight=TARGET_WEIGHT, random_state=SEED
    )
    return vectors.ids, unit_square(model.fit_transform(matrix, y=labels))


@dataclass
class Region:
    id: str
    level: int
    parent: str | None
    x: float
    y: float
    n: int


def regions(xy: np.ndarray, levels: tuple[int, ...] = LEVELS, seed: int = SEED) -> tuple[np.ndarray, list[Region]]:
    """The finest region of every point, and the nested regions of all levels (coarsest first)."""
    from sklearn.cluster import KMeans

    finest = len(levels)
    cells = KMeans(n_clusters=levels[-1], n_init=3, random_state=seed).fit(xy)
    member = cells.labels_
    weight = np.bincount(member, minlength=levels[-1]).astype(float)
    centres = np.array([xy[member == k].mean(axis=0) for k in range(levels[-1])])
    # parent_of[level][k]: the region one level up of region k of that level.
    parent_of: dict[int, np.ndarray] = {}
    level_centres, level_weight = {finest: centres}, {finest: weight}
    for level in range(finest - 1, 0, -1):
        groups = KMeans(n_clusters=levels[level - 1], n_init=5, random_state=seed)
        groups.fit(level_centres[level + 1], sample_weight=level_weight[level + 1])
        parent_of[level + 1] = groups.labels_
        size = np.bincount(groups.labels_, weights=level_weight[level + 1], minlength=levels[level - 1])
        level_centres[level] = np.array([
            np.average(level_centres[level + 1][groups.labels_ == k], axis=0, weights=level_weight[level + 1][groups.labels_ == k])
            for k in range(levels[level - 1])
        ])
        level_weight[level] = size
    out = []
    for level in range(1, finest + 1):
        for k, (x, y) in enumerate(level_centres[level]):
            n = int(level_weight[level][k])
            if not n:
                continue
            parent = f"r{level - 1}.{parent_of[level][k]}" if level > 1 else None
            out.append(Region(f"r{level}.{k}", level, parent, round(float(x), 5), round(float(y), 5), n))
    return member, out


def chain(regions_: list[Region]) -> dict[str, list[str]]:
    """Each region's id with its ancestors, coarsest first."""
    by_id = {region.id: region for region in regions_}
    out = {}
    for region in regions_:
        path, at = [], region
        while at:
            path.append(at.id)
            at = by_id.get(at.parent) if at.parent else None
        out[region.id] = path[::-1]
    return out


def distinctive_words(texts_by_region: dict[str, list[str]], top: int = 10) -> dict[str, list[str]]:
    """The words most typical of each region against all regions: class-based TF-IDF over the English texts."""
    counts = {region: Counter(_words(" ".join(texts))) for region, texts in texts_by_region.items()}
    spread = Counter(word for words in counts.values() for word in words)
    total = len(counts)
    out = {}
    for region, words in counts.items():
        size = sum(words.values()) or 1
        scored = sorted(words, key=lambda word: -(words[word] / size) * math.log(1 + total / spread[word]))
        out[region] = [word for word in scored if words[word] >= 3][:top]
    return out


def _words(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z][a-z'-]{2,}", fold(text)) if word not in _STOP]


def sample_titles(ids: list[str], xy: np.ndarray, centre: tuple[float, float], texts: dict[str, str], seed: str) -> list[str]:
    """The titles nearest a region's centre, then a random sample of the others, without repeats."""
    order = np.argsort(((xy - np.array(centre)) ** 2).sum(axis=1))
    central = [ids[i] for i in order[:CENTRAL_TITLES]]
    rest = [ids[i] for i in order[CENTRAL_TITLES:]]
    random.Random(seed).shuffle(rest)
    seen, out = set(), []
    for record_id in central + rest:
        text = texts.get(record_id, "")
        key = fold(text)
        if text and key not in seen:
            seen.add(key)
            out.append(text)
        if len(out) >= CENTRAL_TITLES + SAMPLED_TITLES:
            break
    return out


INSTRUCTIONS = (
    "You name regions on a map of the Bibliography of Belgian History, a bibliography of publications on the "
    "history of Belgium and the territories before it, from Antiquity to the present. Publications on similar "
    "subjects lie close together on the map.\n\n"
    "Give the region below a short name of one to five words, as a historian would title a section of a "
    "bibliography. Name the shared subject concretely: a topic, an institution, a group, a kind of source, a "
    "place or a period, or a combination ('Béguinages', 'Colonial Congo', 'Parish registers and genealogy', "
    "'Liège in the Middle Ages'). Never use 'history', 'Belgian' or 'Belgium' on their own as the name, and do "
    "not list several unrelated subjects. If the titles mix subjects, name the one most of them share.\n\n"
    "Answer with JSON only, with the keys \"en\", \"nl\" and \"fr\": the same name in English, Dutch and French, "
    "each in the usual terms of historians writing in that language."
)


def cell_prompt(titles: list[str], words: list[str]) -> str:
    listed = "\n".join(f"- {title}" for title in titles)
    return f"{INSTRUCTIONS}\n\nMost distinctive words: {', '.join(words)}\n\nTitles in this region (English translations):\n{listed}"


def region_prompt(parts: list[tuple[str, int]], titles: list[str]) -> str:
    named = "\n".join(f"- {name} ({n} titles)" for name, n in parts)
    listed = "\n".join(f"- {title}" for title in titles)
    return (
        f"{INSTRUCTIONS}\n\nThis is a larger region of the map. It covers these smaller regions; give it a name "
        f"that covers most of them, broader than each:\n{named}\n\nSome titles from the region:\n{listed}\n\n"
        "This name is printed large on the map, like the name of a country: use at most three words in each "
        "language ('Colonial Congo', 'Parish and village', 'The two world wars'), name what sets this region apart "
        "from the others rather than what all of Belgian history shares (avoid 'Low Countries' and 'Southern "
        "Netherlands' unless the region is about them as such), and write it in sentence case: a capital only "
        "for the first word and for proper names."
    )


def parse_name(answer: str) -> dict[str, str] | None:
    """The {"en", "nl", "fr"} name in a model answer, or None."""
    found = re.search(r"\{.*\}", answer, re.DOTALL)
    if not found:
        return None
    try:
        value = json.loads(found.group(0))
    except json.JSONDecodeError:
        return None
    names = {key: squash(str(value.get(key) or "")).strip(" .\"'") for key in ("en", "nl", "fr")}
    if not all(names.values()) or any(len(name) > 90 for name in names.values()):
        return None
    return names


class Namer:
    """The local model, loaded on first use, with every answer cached by its prompt."""

    def __init__(self, cache: Path, log=print):
        self.cache_path = cache
        self.log = log
        self.cache: dict[str, str] = {}
        if cache.exists():
            for line in cache.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.cache[row["key"]] = row["answer"]
        self.model = self.tokenizer = None

    @staticmethod
    def key(prompt: str) -> str:
        return hashlib.sha1(f"{MODEL}@{REVISION}\n{prompt}".encode("utf-8")).hexdigest()

    def ask(self, prompt: str) -> str:
        return self.ask_many([prompt])[0]

    def ask_many(self, prompts: list[str], batch: int = 8) -> list[str]:
        """The answers to ``prompts``, the new ones generated a batch at a time (greedy decoding)."""
        todo = [prompt for prompt in dict.fromkeys(prompts) if self.key(prompt) not in self.cache]
        if todo and self.model is None:
            from mlx_lm import load

            self.log(f"topicmap: loading {MODEL}@{REVISION[:8]}")
            self.model, self.tokenizer = load(MODEL, revision=REVISION, tokenizer_config={"fix_mistral_regex": True})
        for start in range(0, len(todo), batch):
            from mlx_lm import batch_generate

            chunk = todo[start : start + batch]
            tokens = [
                self.tokenizer.apply_chat_template([{"role": "user", "content": prompt}], add_generation_prompt=True)
                for prompt in chunk
            ]
            answers = batch_generate(self.model, self.tokenizer, tokens, max_tokens=120).texts
            with self.cache_path.open("a", encoding="utf-8") as handle:
                for prompt, answer in zip(chunk, answers):
                    self.cache[self.key(prompt)] = answer
                    handle.write(json.dumps({"key": self.key(prompt), "answer": answer}, ensure_ascii=False) + "\n")
        return [self.cache[self.key(prompt)] for prompt in prompts]


def name_regions(
    ids: list[str], xy: np.ndarray, member: np.ndarray, regions_: list[Region], texts: dict[str, str], namer: Namer, log=print
) -> dict[str, dict[str, str]]:
    """Names for every region, finest level first, each coarser one from the names of its parts."""
    finest = max(region.level for region in regions_)
    paths = chain(regions_)
    leaf_of = np.array([f"r{finest}.{k}" for k in member])
    members: dict[str, list[int]] = {}
    for index, leaf in enumerate(leaf_of):
        for region_id in paths[leaf]:
            members.setdefault(region_id, []).append(index)
    cells = [region for region in regions_ if region.level == finest]
    words = distinctive_words({region.id: [texts.get(ids[i], "") for i in members[region.id]] for region in cells})
    names: dict[str, dict[str, str]] = {}
    for level in range(finest, 0, -1):
        todo = [region for region in regions_ if region.level == level]
        prompts = []
        for region in todo:
            rows = members[region.id]
            titles = sample_titles([ids[i] for i in rows], xy[rows], (region.x, region.y), texts, region.id)
            if level == finest:
                prompts.append(cell_prompt(titles, words.get(region.id, [])))
            else:
                parts = sorted((r for r in regions_ if r.parent == region.id), key=lambda r: -r.n)
                prompts.append(region_prompt([(names[r.id]["en"], r.n) for r in parts if r.id in names], titles[:15]))
        for start in range(0, len(todo), 48):
            answers = namer.ask_many(prompts[start : start + 48])
            for region, answer in zip(todo[start : start + 48], answers):
                if name := parse_name(answer):
                    names[region.id] = name
            log(f"topicmap: level {level}, {min(start + 48, len(todo))} of {len(todo)} named")
    return names


def apply(records: list[Record], ids: list[str], xy: np.ndarray, member: np.ndarray, finest: int) -> int:
    """Write each placed entry's position and finest region into its record; clear them on the others."""
    where = {record_id: (xy[i], int(member[i])) for i, record_id in enumerate(ids)}
    count = 0
    for record in records:
        found = where.get(record.id)
        record.topic_xy = [round(float(found[0][0]), 5), round(float(found[0][1]), 5)] if found else []
        record.topic = f"r{finest}.{found[1]}" if found else None
        count += bool(found)
    return count


def fix_names(names: dict[str, dict[str, str]], fixes: Path) -> int:
    """Apply the hand corrections of ``data/curated/topic_name_fixes.csv`` (language, wrong, right): a name that is
    exactly ``wrong`` in that language becomes ``right``. Returns the number of names corrected."""
    import csv

    if not fixes.exists():
        return 0
    with fixes.open(encoding="utf-8", newline="") as handle:
        rows = {(row["language"], row["wrong"]): row["right"] for row in csv.DictReader(handle)}
    count = 0
    for name in names.values():
        for language, value in list(name.items()):
            if (language, value) in rows:
                name[language] = rows[(language, value)]
                count += 1
    return count


def regions_document(regions_: list[Region], names: dict[str, dict[str, str]]) -> dict:
    """The committed regions file: the tree, centres, sizes and names, and how they were made."""
    return {
        "about": "Regions of the topic map (bhb topicmap): nested k-means cells on the UMAP layout, named by "
        f"{MODEL}@{REVISION} (machine-made names, not checked by hand).",
        "levels": list(LEVELS),
        "regions": [
            {"id": r.id, "level": r.level, "parent": r.parent, "x": r.x, "y": r.y, "n": r.n, **({"name": names[r.id]} if r.id in names else {})}
            for r in regions_
        ],
    }
