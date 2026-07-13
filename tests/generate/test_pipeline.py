from pathlib import Path

from generate import pipeline
from generate.pipeline import answer_question
from generate.schema import GeneratedAnswer


def test_answer_question_reuses_one_text_fetch_for_rerank_and_generation(monkeypatch):
    calls = {"get_chunk_texts": 0}

    def fake_retrieve(bm25_dir, vector_db_path, question, config):
        return ["a", "b", "c"]

    def fake_get_chunk_texts(vector_db_path, chunk_ids):
        calls["get_chunk_texts"] += 1
        return {"a": "text a", "b": "text b", "c": "text c"}

    def fake_rerank(question, candidates, config):
        return ["b"]  # narrows top-n down to top-k

    captured_chunks = {}

    def fake_generate_answer(client, question, chunks, config):
        captured_chunks["chunks"] = chunks
        return GeneratedAnswer(answer_text="...", citations=["b"])

    monkeypatch.setattr(pipeline, "hybrid_retrieve", fake_retrieve)
    monkeypatch.setattr(pipeline, "get_chunk_texts", fake_get_chunk_texts)
    monkeypatch.setattr(pipeline, "rerank", fake_rerank)
    monkeypatch.setattr(pipeline, "generate_answer", fake_generate_answer)

    from config.settings import Settings

    settings = Settings(anthropic_api_key="placeholder")

    result = answer_question(
        "q",
        client=object(),
        bm25_dir=Path("unused"),
        vector_db_path=Path("unused"),
        settings=settings,
    )

    assert calls["get_chunk_texts"] == 1  # reused for both rerank input and generation input
    assert captured_chunks["chunks"] == [("b", "text b")]
    assert result.citations == ["b"]
