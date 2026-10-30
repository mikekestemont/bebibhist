import numpy as np

from bhb.io_utils import record_from_dict
from bhb.model import Host, Person, Record
from bhb.similar import Vectors, apply, embed_text, neighbours


def _record(record_id: str, title: str | None, **extra) -> Record:
    return Record(id=record_id, source="print-straive", bgb_year=2000, title=title, **extra)


def test_embed_text_uses_titles_only_and_skips_stubs():
    record = _record(
        "bhb:2000-1",
        "Les béguinages",
        subtitle="une enquête",
        title_translated="De begijnhoven",
        persons=[Person("Van Aert", "Wout")],
        host=Host(title="Revue du Nord"),
    )
    assert embed_text(record) == "Les béguinages. une enquête. De begijnhoven"
    assert embed_text(_record("bhb:2000-2", "Inleiding")) is None
    assert embed_text(_record("bhb:2000-3", None)) is None
    assert embed_text(_record("bhb:2000-4", "Les béguinages", is_cross_listing=True)) is None
    assert embed_text(_record("bhb:2000-5", "Les béguinages", role="host")) is None


def test_neighbours_skip_the_record_itself_and_records_of_the_same_text():
    matrix = np.array(
        [[1.0, 0.0], [1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [0.7, 0.7]],
        dtype=np.float32,
    )
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    vectors = Vectors(
        ids=["a", "a-again", "b", "c", "d"],
        texts=["Les béguinages", "Les Béguinages.", "Beguines in Flanders", "Spoorwegen", "Begijnen en spoorwegen"],
        matrix=matrix,
    )
    found = neighbours(vectors, k=2, chunk=2)
    assert [record_id for record_id, _ in found["a"]] == ["b", "d"]
    assert [record_id for record_id, _ in found["c"]] == ["d", "b"]
    assert all(-1.0 <= score <= 1.0 for _, score in found["a"])


def test_apply_writes_ids_and_scores_that_survive_a_round_trip():
    record = _record("bhb:2000-1", "Les béguinages")
    assert apply([record], {"bhb:2000-1": [("bhb:2000-2", 0.91), ("bhb:2000-3", 0.88)]}) == 1
    restored = record_from_dict(record.to_dict())
    assert restored.similar == ["bhb:2000-2", "bhb:2000-3"]
    assert restored.similar_scores == [0.91, 0.88]


def test_language_of_reads_function_words_and_leaves_bilingual_titles_out():
    from bhb.similar import language_of

    assert language_of("Les béguinages de Flandre") == "fr"
    assert language_of("Het begijnhof van Gent") == "nl"
    assert language_of("Het begijnhof van Gent. Le béguinage de Gand") is None
    assert language_of("Vesalius") is None


def test_quality_counts_shared_codes_and_language_switches():
    from bhb.model import Category
    from bhb.similar import quality

    def coded(record_id, title, code):
        return _record(record_id, title, categories=[Category(code=code, source="vsmart", primary=True)])

    records = [
        coded("a", "Les béguinages de Flandre", "III.B.1.d."),
        coded("b", "Het begijnhof van Gent", "III.B.1.d."),
        coded("c", "La guerre de 1914", "III.D.1.e."),
    ]
    scores = quality(records, {"a": [("b", 0.9), ("c", 0.8)]})
    assert scores["same_period"] == 0.5
    assert scores["same_section"] == 0.5
    assert scores["other_language"] == 0.5


def test_a_shared_rare_name_lifts_a_neighbour_above_a_closer_subject():
    angle = np.radians([0, 35, 30] + [90 + 3 * n for n in range(30)])
    matrix = np.stack([np.cos(angle), np.sin(angle)], axis=1).astype(np.float32)
    texts = ["Guibert de Gembloux et son monastère", "Hildegard and Guibert of Gembloux", "Les moines de Villers en Brabant"]
    texts += [f"Guibert {n}" if n < 2 else f"Filler title number {n} spoorwegen" for n in range(30)]
    vectors = Vectors(ids=[f"r{n}" for n in range(len(texts))], texts=texts, matrix=matrix)
    found = neighbours(vectors, k=1)
    # r2 is closer in meaning (cosine), but r1 shares the rare words Guibert and Gembloux.
    assert found["r0"][0][0] == "r1"
    assert found["r0"][0][1] > float(matrix[0] @ matrix[1])
