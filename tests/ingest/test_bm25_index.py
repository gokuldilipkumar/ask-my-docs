from ingest.bm25_index import build_bm25_index, load_bm25_index, search_bm25


def test_bm25_roundtrip_finds_expected_chunk(make_chunk, tmp_path):
    chunks = [
        make_chunk("a", "Slow flight and stall speed procedures."),
        make_chunk("b", "Crosswind takeoff and landing techniques."),
        make_chunk("c", "Weight and balance calculations for the airplane."),
    ]
    index_dir = tmp_path / "bm25"
    build_bm25_index(chunks, index_dir)

    index, corpus_ids = load_bm25_index(index_dir)
    results = search_bm25(index, corpus_ids, "stall speed", top_k=1)

    assert results[0] == "a"
