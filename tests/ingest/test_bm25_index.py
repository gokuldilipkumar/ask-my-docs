from ingest.bm25_index import build_bm25_index, load_bm25_index, search_bm25
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


def test_bm25_roundtrip_finds_expected_chunk(tmp_path):
    chunks = [
        _chunk("a", "Slow flight and stall speed procedures."),
        _chunk("b", "Crosswind takeoff and landing techniques."),
        _chunk("c", "Weight and balance calculations for the airplane."),
    ]
    index_dir = tmp_path / "bm25"
    build_bm25_index(chunks, index_dir)

    index, corpus_ids = load_bm25_index(index_dir)
    results = search_bm25(index, corpus_ids, "stall speed", top_k=1)

    assert results[0] == "a"
