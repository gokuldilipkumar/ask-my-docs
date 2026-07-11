import pytest

from ingest.vector_index import build_vector_index, search_vector


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
