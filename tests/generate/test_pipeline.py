from pathlib import Path

from config.settings import ObservabilityConfig, Settings
from generate import pipeline
from generate.pipeline import answer_question
from generate.schema import GeneratedAnswer
from observability.context import ObservabilityContext
from observability.tracer import NoOpTracer


def test_answer_question_reuses_one_text_fetch_for_rerank_and_generation(monkeypatch):
    calls = {"get_chunk_texts": 0}

    def fake_retrieve(bm25_dir, vector_db_path, question, config, observability=None):
        return ["a", "b", "c"]

    def fake_get_chunk_texts(vector_db_path, chunk_ids):
        calls["get_chunk_texts"] += 1
        return {"a": "text a", "b": "text b", "c": "text c"}

    def fake_rerank(question, candidates, config, observability=None):
        return ["b"]  # narrows top-n down to top-k

    captured_chunks = {}

    def fake_generate_answer(client, question, chunks, config, observability=None):
        captured_chunks["chunks"] = chunks
        return GeneratedAnswer(answer_text="...", citations=["b"])

    monkeypatch.setattr(pipeline, "hybrid_retrieve", fake_retrieve)
    monkeypatch.setattr(pipeline, "get_chunk_texts", fake_get_chunk_texts)
    monkeypatch.setattr(pipeline, "rerank", fake_rerank)
    monkeypatch.setattr(pipeline, "generate_answer", fake_generate_answer)

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


def test_answer_question_handles_empty_retrieval_without_querying_texts(monkeypatch):
    # get_chunk_texts([]) crashes (LanceDB rejects "WHERE chunk_id IN ()" as invalid
    # SQL) - answer_question must short-circuit before ever calling it. rerank is
    # fine to call with an empty candidate list (Block 3: it returns [] without
    # loading the model), so only get_chunk_texts needs to be provably unreached.
    def fake_retrieve(bm25_dir, vector_db_path, question, config, observability=None):
        return []

    def exploding_get_chunk_texts(vector_db_path, chunk_ids):
        raise AssertionError("must not call get_chunk_texts when retrieval found nothing")

    def fake_rerank(question, candidates, config, observability=None):
        assert candidates == []
        return []

    captured_chunks = {}

    def fake_generate_answer(client, question, chunks, config, observability=None):
        captured_chunks["chunks"] = chunks
        return GeneratedAnswer(answer_text="I don't have information about that.", citations=[])

    monkeypatch.setattr(pipeline, "hybrid_retrieve", fake_retrieve)
    monkeypatch.setattr(pipeline, "get_chunk_texts", exploding_get_chunk_texts)
    monkeypatch.setattr(pipeline, "rerank", fake_rerank)
    monkeypatch.setattr(pipeline, "generate_answer", fake_generate_answer)

    settings = Settings(anthropic_api_key="placeholder")

    result = answer_question(
        "q",
        client=object(),
        bm25_dir=Path("unused"),
        vector_db_path=Path("unused"),
        settings=settings,
    )

    assert captured_chunks["chunks"] == []
    assert result.citations == []


def test_answer_question_passes_one_shared_observability_context_to_every_stage(monkeypatch):
    calls = []

    def fake_hybrid_retrieve(bm25_dir, vector_db_path, question, config, observability=None):
        calls.append(("hybrid_retrieve", observability))
        return ["a"]

    def fake_get_chunk_texts(vector_db_path, chunk_ids):
        return {cid: "text" for cid in chunk_ids}

    def fake_rerank(question, candidates, config, observability=None):
        calls.append(("rerank", observability))
        return [cid for cid, _ in candidates]

    def fake_generate_answer(client, question, chunks, config, observability=None):
        calls.append(("generate_answer", observability))
        return GeneratedAnswer(answer_text="x", citations=[])

    monkeypatch.setattr(pipeline, "hybrid_retrieve", fake_hybrid_retrieve)
    monkeypatch.setattr(pipeline, "get_chunk_texts", fake_get_chunk_texts)
    monkeypatch.setattr(pipeline, "rerank", fake_rerank)
    monkeypatch.setattr(pipeline, "generate_answer", fake_generate_answer)

    given = ObservabilityContext(tracer=NoOpTracer(), config=ObservabilityConfig())
    settings = Settings(anthropic_api_key="placeholder")

    answer_question(
        "q", client=object(), bm25_dir=Path("unused"), vector_db_path=Path("unused"),
        settings=settings, observability=given,
    )

    assert [c[1] for c in calls] == [given, given, given]  # same instance, not three separate ones
