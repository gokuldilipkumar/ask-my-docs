import pytest

from ingest.vector_index import build_vector_index, get_chunk_texts, search_vector


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
