from pathlib import Path

from citations import pipeline
from citations.pipeline import answer_with_verified_citations
from citations.schema import VerifiedAnswer
from config.settings import Settings
from generate.schema import GeneratedAnswer


def test_answer_with_verified_citations_fetches_cited_subset_and_verifies(monkeypatch):
    def fake_answer_question(question, client, bm25_dir, vector_db_path, settings, observability=None):
        return GeneratedAnswer(answer_text="Stalls happen when...", citations=["b"])

    calls = {"get_chunk_texts": 0}

    def fake_get_chunk_texts(vector_db_path, chunk_ids):
        calls["get_chunk_texts"] += 1
        assert chunk_ids == ["b"]
        return {"b": "text b"}

    captured = {}

    def fake_verify_citations(client, question, answer, chunk_texts, config, observability=None):
        captured["chunk_texts"] = chunk_texts
        return VerifiedAnswer(answer_text=answer.answer_text, citations=["b"], coverage=1.0, low_confidence=False)

    monkeypatch.setattr(pipeline, "answer_question", fake_answer_question)
    monkeypatch.setattr(pipeline, "get_chunk_texts", fake_get_chunk_texts)
    monkeypatch.setattr(pipeline, "verify_citations", fake_verify_citations)

    settings = Settings(anthropic_api_key="placeholder")

    result = answer_with_verified_citations(
        "q", client=object(), bm25_dir=Path("unused"), vector_db_path=Path("unused"), settings=settings
    )

    assert calls["get_chunk_texts"] == 1
    assert captured["chunk_texts"] == {"b": "text b"}
    assert result.citations == ["b"]


def test_answer_with_verified_citations_skips_text_fetch_when_no_citations(monkeypatch):
    def fake_answer_question(question, client, bm25_dir, vector_db_path, settings, observability=None):
        return GeneratedAnswer(answer_text="I don't have information about that.", citations=[])

    def exploding_get_chunk_texts(vector_db_path, chunk_ids):
        raise AssertionError("must not fetch chunk text when there are no citations to verify")

    captured = {}

    def fake_verify_citations(client, question, answer, chunk_texts, config, observability=None):
        captured["chunk_texts"] = chunk_texts
        return VerifiedAnswer(answer_text=answer.answer_text, citations=[], coverage=1.0, low_confidence=False)

    monkeypatch.setattr(pipeline, "answer_question", fake_answer_question)
    monkeypatch.setattr(pipeline, "get_chunk_texts", exploding_get_chunk_texts)
    monkeypatch.setattr(pipeline, "verify_citations", fake_verify_citations)

    settings = Settings(anthropic_api_key="placeholder")

    result = answer_with_verified_citations(
        "q", client=object(), bm25_dir=Path("unused"), vector_db_path=Path("unused"), settings=settings
    )

    assert captured["chunk_texts"] == {}
    assert result.citations == []


def test_answer_with_verified_citations_passes_one_shared_observability_to_both_stages(monkeypatch):
    calls = []

    def fake_answer_question(question, client, bm25_dir, vector_db_path, settings, observability=None):
        calls.append(("answer_question", observability))
        return GeneratedAnswer(answer_text="x", citations=[])

    def fake_verify_citations(client, question, answer, chunk_texts, config, observability=None):
        calls.append(("verify_citations", observability))
        return VerifiedAnswer(answer_text=answer.answer_text, citations=[], coverage=1.0, low_confidence=False)

    monkeypatch.setattr(pipeline, "answer_question", fake_answer_question)
    monkeypatch.setattr(pipeline, "verify_citations", fake_verify_citations)

    settings = Settings(anthropic_api_key="placeholder")

    answer_with_verified_citations(
        "q", client=object(), bm25_dir=Path("unused"), vector_db_path=Path("unused"), settings=settings
    )

    observabilities = [c[1] for c in calls]
    assert observabilities[0] is not None
    assert observabilities[0] is observabilities[1]  # same instance, not two separate ones
