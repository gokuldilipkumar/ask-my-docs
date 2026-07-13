from pathlib import Path

import lancedb
from sentence_transformers import SentenceTransformer

from ingest.models import Chunk

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME, device="cpu")
    return _model


def build_vector_index(chunks: list[Chunk], db_path: Path) -> None:
    model = _get_model()
    embeddings = model.encode([c.text for c in chunks], normalize_embeddings=True)

    rows = [
        {
            "chunk_id": chunk.chunk_id,
            "text": chunk.text,
            "vector": embedding.tolist(),
        }
        for chunk, embedding in zip(chunks, embeddings)
    ]

    db = lancedb.connect(str(db_path))
    db.create_table("chunks", data=rows, mode="overwrite")


def get_chunk_texts(db_path: Path, chunk_ids: list[str]) -> dict[str, str]:
    db = lancedb.connect(str(db_path))
    table = db.open_table("chunks")
    # chunk_ids are content hashes (hex), safe to embed in the filter string.
    # No .limit(): the table can hold duplicate chunk_ids (BUGS.md), so a limit
    # sized to len(chunk_ids) would silently truncate the scan before later rows.
    id_list = ", ".join(f"'{cid}'" for cid in chunk_ids)
    rows = table.search().where(f"chunk_id IN ({id_list})").to_list()
    texts = {r["chunk_id"]: r["text"] for r in rows}
    missing = [cid for cid in chunk_ids if cid not in texts]
    if missing:
        raise KeyError(f"chunk_ids not found in index: {missing}")
    return texts


def search_vector(db_path: Path, query: str, top_k: int) -> list[str]:
    model = _get_model()
    query_vector = model.encode(query, normalize_embeddings=True).tolist()

    db = lancedb.connect(str(db_path))
    table = db.open_table("chunks")
    results = table.search(query_vector).limit(top_k).to_list()
    return [r["chunk_id"] for r in results]
