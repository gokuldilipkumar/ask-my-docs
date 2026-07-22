import pytest

from ingest import vector_index
from ingest.vector_index import build_vector_index, get_chunk_texts, search_vector


def test_warm_model_loads_the_embedding_model_once(monkeypatch):
    monkeypatch.setattr(vector_index, "_model", None)
    calls = []

    class FakeSentenceTransformer:
        def __init__(self, name, device):
            calls.append((name, device))

    monkeypatch.setattr(vector_index, "SentenceTransformer", FakeSentenceTransformer)

    vector_index.warm_model()
    vector_index.warm_model()  # idempotent -- second call must not construct again

    assert len(calls) == 1


@pytest.mark.slow
def test_vector_search_finds_semantically_closest_chunk(make_chunk, tmp_path):
    chunks = [
        make_chunk("a", "The stall occurs when the critical angle of attack is exceeded."),
        make_chunk("b", "Weight and balance must be computed before every flight."),
        make_chunk("c", "Radio communication procedures at towered airports."),
    ]
    db_path = tmp_path / "lancedb"

    build_vector_index(chunks, db_path)
    results = search_vector(db_path, "What causes an aerodynamic stall?", top_k=1)

    assert results[0] == "a"


@pytest.mark.slow
def test_get_chunk_texts_returns_texts_keyed_by_id(make_chunk, tmp_path):
    chunks = [
        make_chunk("a", "Text about aerodynamic stalls."),
        make_chunk("b", "Text about crosswind landings."),
    ]
    db_path = tmp_path / "lancedb"
    build_vector_index(chunks, db_path)

    texts = get_chunk_texts(db_path, ["b", "a"])

    assert texts == {
        "a": "Text about aerodynamic stalls.",
        "b": "Text about crosswind landings.",
    }


@pytest.mark.slow
def test_get_chunk_texts_raises_on_unknown_id(make_chunk, tmp_path):
    db_path = tmp_path / "lancedb"
    build_vector_index([make_chunk("a", "Some text.")], db_path)

    with pytest.raises(KeyError):
        get_chunk_texts(db_path, ["a", "missing-id"])


@pytest.mark.slow
def test_get_chunk_texts_id_with_quote_cannot_corrupt_the_filter(make_chunk, tmp_path):
    db_path = tmp_path / "lancedb"
    build_vector_index([make_chunk("a", "Some text.")], db_path)

    # a quote in an id must yield the normal missing-id KeyError,
    # not a syntax error from a corrupted filter string
    with pytest.raises(KeyError):
        get_chunk_texts(db_path, ["it's-not-here"])


@pytest.mark.slow
def test_get_chunk_texts_tolerates_duplicate_chunk_ids_in_table(make_chunk, tmp_path):
    # The real corpus currently contains duplicate chunk_ids (repeated section
    # titles collide in make_chunk_id — tracked in BUGS.md). A scan limit sized
    # to len(chunk_ids) silently truncates when duplicates inflate the match
    # count, hiding rows stored later — found by Block 3's real-corpus spot-check.
    chunks = [
        make_chunk("dup", "First duplicate text."),
        make_chunk("dup", "Second duplicate text."),
        make_chunk("unique", "Unique text."),
    ]
    db_path = tmp_path / "lancedb"
    build_vector_index(chunks, db_path)

    texts = get_chunk_texts(db_path, ["dup", "unique"])

    assert texts["unique"] == "Unique text."
