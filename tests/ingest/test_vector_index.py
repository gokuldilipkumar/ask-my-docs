import pytest

from ingest.vector_index import build_vector_index, search_vector
from ingest.models import Chunk


def _chunk(chunk_id, text):
    return Chunk(
        chunk_id=chunk_id,
        chapter_number=4,
        chapter_title="Energy Management",
        section_title="Total Energy",
        page_index_start=0,
        page_index_end=0,
        text=text,
        token_count=len(text.split()),
        sequence=0,
    )


@pytest.mark.slow
def test_vector_search_finds_semantically_closest_chunk(tmp_path):
    chunks = [
        _chunk("a", "The stall occurs when the critical angle of attack is exceeded."),
        _chunk("b", "Weight and balance must be computed before every flight."),
        _chunk("c", "Radio communication procedures at towered airports."),
    ]
    db_path = tmp_path / "lancedb"

    build_vector_index(chunks, db_path)
    results = search_vector(db_path, "What causes an aerodynamic stall?", top_k=1)

    assert results[0] == "a"
