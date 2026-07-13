from pathlib import Path

from config.settings import Settings
from generate.client import generate_answer
from generate.schema import GeneratedAnswer
from ingest.vector_index import get_chunk_texts
from rerank.cross_encoder import rerank
from retrieval.hybrid import hybrid_retrieve


def answer_question(
    question: str, client, bm25_dir: Path, vector_db_path: Path, settings: Settings
) -> GeneratedAnswer:
    top_n_ids = hybrid_retrieve(bm25_dir, vector_db_path, question, settings.retrieval)
    texts = get_chunk_texts(vector_db_path, top_n_ids) if top_n_ids else {}
    top_k_ids = rerank(question, [(cid, texts[cid]) for cid in top_n_ids], settings.rerank)
    chunks = [(cid, texts[cid]) for cid in top_k_ids]
    return generate_answer(client, question, chunks, settings.generation)
