import pytest

from config.settings import ObservabilityConfig, RetrievalConfig
from ingest.bm25_index import build_bm25_index
from ingest.vector_index import build_vector_index
from observability.context import ObservabilityContext
from retrieval.hybrid import hybrid_retrieve


@pytest.mark.slow
def test_hybrid_retrieve_fuses_and_truncates_to_top_n(tmp_path, make_chunk):
    chunks = [
        make_chunk("a", "The stall occurs when the critical angle of attack is exceeded."),
        make_chunk("b", "Weight and balance must be computed before every flight."),
        make_chunk("c", "Radio communication procedures at towered airports."),
        make_chunk("d", "Crosswind takeoff and landing techniques for the airplane."),
        make_chunk("e", "Slow flight and stall speed procedures during training."),
    ]
    bm25_dir = tmp_path / "bm25"
    vector_dir = tmp_path / "lancedb"
    build_bm25_index(chunks, bm25_dir)
    build_vector_index(chunks, vector_dir)

    config = RetrievalConfig(rrf_k=60, bm25_weight=1.0, vector_weight=1.0, top_n=2)
    results = hybrid_retrieve(bm25_dir, vector_dir, "What causes an aerodynamic stall?", config)

    assert len(results) == 2
    assert "a" in results  # the direct stall-content chunk should surface


@pytest.mark.slow
def test_changing_fusion_weights_changes_top_result(tmp_path, make_chunk):
    # "b" alone contains the exact keyword "stall" (favors BM25) but is
    # semantically off-topic; "a" describes a stall without using the word
    # (favors vector). Margins verified against the real model at build time:
    # BM25 b=0.46 vs a=0.0; vector a=0.70 vs b=0.60.
    chunks = [
        make_chunk("a", "Exceeding the critical angle of attack makes the wing stop producing lift."),
        make_chunk("b", "stall stall stall invoice paperwork filing cabinet office supplies."),
    ]
    bm25_dir = tmp_path / "bm25"
    vector_dir = tmp_path / "lancedb"
    build_bm25_index(chunks, bm25_dir)
    build_vector_index(chunks, vector_dir)

    favor_bm25 = RetrievalConfig(rrf_k=60, bm25_weight=5.0, vector_weight=0.01, top_n=2)
    favor_vector = RetrievalConfig(rrf_k=60, bm25_weight=0.01, vector_weight=5.0, top_n=2)

    query = "What causes an aerodynamic stall?"
    results_bm25 = hybrid_retrieve(bm25_dir, vector_dir, query, favor_bm25)
    results_vector = hybrid_retrieve(bm25_dir, vector_dir, query, favor_vector)

    assert results_bm25[0] == "b"
    assert results_vector[0] == "a"


@pytest.mark.slow
def test_hybrid_retrieve_opens_spans_for_bm25_vector_and_fusion(tmp_path, make_chunk, spy_tracer):
    chunks = [
        make_chunk("a", "The stall occurs when the critical angle of attack is exceeded."),
        make_chunk("b", "Weight and balance must be computed before every flight."),
    ]
    bm25_dir = tmp_path / "bm25"
    vector_dir = tmp_path / "lancedb"
    build_bm25_index(chunks, bm25_dir)
    build_vector_index(chunks, vector_dir)

    config = RetrievalConfig(rrf_k=60, bm25_weight=1.0, vector_weight=1.0, top_n=2)
    observability = ObservabilityContext(tracer=spy_tracer, config=ObservabilityConfig())

    hybrid_retrieve(bm25_dir, vector_dir, "What causes a stall?", config, observability=observability)

    assert [s["name"] for s in spy_tracer.spans] == [
        "retrieval.bm25.search", "retrieval.vector.search", "retrieval.fusion.rrf"
    ]
