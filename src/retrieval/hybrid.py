from pathlib import Path

from config.settings import RetrievalConfig
from ingest.bm25_index import load_bm25_index, search_bm25
from ingest.vector_index import search_vector
from observability.context import ObservabilityContext, noop_observability
from retrieval.fusion import reciprocal_rank_fusion


def hybrid_retrieve(
    bm25_index_dir: Path, vector_db_path: Path, query: str, config: RetrievalConfig,
    observability: ObservabilityContext | None = None,
) -> list[str]:
    observability = observability or noop_observability()
    tracer = observability.tracer

    with tracer.span("retrieval.bm25.search"):
        bm25_index, corpus_ids = load_bm25_index(bm25_index_dir)
        bm25_ranking = search_bm25(bm25_index, corpus_ids, query, top_k=config.top_n)
    with tracer.span("retrieval.vector.search"):
        vector_ranking = search_vector(vector_db_path, query, top_k=config.top_n)
    with tracer.span("retrieval.fusion.rrf"):
        fused = reciprocal_rank_fusion(
            [bm25_ranking, vector_ranking],
            weights=[config.bm25_weight, config.vector_weight],
            k=config.rrf_k,
        )
    return fused[: config.top_n]
