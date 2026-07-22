from pathlib import Path

import lancedb
from sentence_transformers import SentenceTransformer

from ingest.models import Chunk

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_TABLE_NAME = "chunks"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME, device="cpu")
    return _model


def warm_model() -> None:
    _get_model()


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
    db.create_table(_TABLE_NAME, data=rows, mode="overwrite")


def _open_table(db_path: Path) -> lancedb.table.Table:
    return lancedb.connect(str(db_path)).open_table(_TABLE_NAME)


def get_chunk_texts(db_path: Path, chunk_ids: list[str]) -> dict[str, str]:
    table = _open_table(db_path)
    # Quotes are SQL-escaped so no id can corrupt the filter string (production
    # ids are hex hashes, but the signature accepts any str). No .limit(): a
    # limit sized to len(chunk_ids) silently truncates the scan when the table
    # holds duplicate ids — ingest forbids duplicates now, but this function
    # must not assume every table it reads was built under that guarantee.
    id_list = ", ".join("'" + cid.replace("'", "''") + "'" for cid in chunk_ids)
    rows = table.search().where(f"chunk_id IN ({id_list})").to_list()
    # if duplicates do exist, an arbitrary row's text wins
    texts = {r["chunk_id"]: r["text"] for r in rows}
    missing = [cid for cid in chunk_ids if cid not in texts]
    if missing:
        raise KeyError(f"chunk_ids not found in index: {missing}")
    return texts


def search_vector(db_path: Path, query: str, top_k: int) -> list[str]:
    model = _get_model()
    query_vector = model.encode(query, normalize_embeddings=True).tolist()

    table = _open_table(db_path)
    results = table.search(query_vector).limit(top_k).to_list()
    return [r["chunk_id"] for r in results]
