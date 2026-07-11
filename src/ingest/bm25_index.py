import json
from pathlib import Path

import bm25s

from ingest.models import Chunk


def build_bm25_index(chunks: list[Chunk], index_dir: Path) -> None:
    corpus = [c.text for c in chunks]
    corpus_ids = [c.chunk_id for c in chunks]

    tokenized = bm25s.tokenize(corpus)
    index = bm25s.BM25()
    index.index(tokenized)

    index_dir.mkdir(parents=True, exist_ok=True)
    index.save(str(index_dir))
    (index_dir / "corpus_ids.json").write_text(json.dumps(corpus_ids))


def load_bm25_index(index_dir: Path) -> tuple[bm25s.BM25, list[str]]:
    index = bm25s.BM25.load(str(index_dir))
    corpus_ids = json.loads((index_dir / "corpus_ids.json").read_text())
    return index, corpus_ids


def search_bm25(index: bm25s.BM25, corpus_ids: list[str], query: str, top_k: int) -> list[str]:
    tokenized_query = bm25s.tokenize(query)
    positions, _scores = index.retrieve(tokenized_query, k=top_k)
    return [corpus_ids[i] for i in positions[0]]
