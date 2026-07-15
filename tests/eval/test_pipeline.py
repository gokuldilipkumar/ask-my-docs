from pathlib import Path

from config.settings import Settings
from eval import pipeline
from eval.pipeline import run_eval
from eval.schema import GoldenQuestion


def _patch_pipeline(monkeypatch, call_counts, answered):
    def fake_hybrid_retrieve(bm25_dir, vector_db_path, question, config):
        call_counts["retrieve"] = call_counts.get("retrieve", 0) + 1
        return ["a"]

    def fake_rerank(question, candidates, config):
        call_counts["rerank"] = call_counts.get("rerank", 0) + 1
        return [cid for cid, _ in candidates]

    def fake_get_chunk_texts(vector_db_path, ids):
        return {cid: "text" for cid in ids}

    def fake_generate_answer(client, question, chunks, config):
        answered.append(question)

        class FakeAnswer:
            answer_text = "answer"
            citations = ["a"]

        return FakeAnswer()

    def fake_verify_citations(client, question, answer, chunk_texts, config):
        class FakeVerified:
            answer_text = answer.answer_text
            citations = answer.citations
            coverage = 1.0
            low_confidence = False

        return FakeVerified()

    def fake_judge_answer(client, question, answer_text, reference_notes, config):
        class FakeJudgment:
            correct = True
            complete = True

        return FakeJudgment()

    def fake_get_cached_result(cache_path, question_id, cfg_hash):
        return None

    def fake_save_cached_result(cache_path, question_id, cfg_hash, result):
        pass

    monkeypatch.setattr(pipeline, "hybrid_retrieve", fake_hybrid_retrieve)
    monkeypatch.setattr(pipeline, "rerank", fake_rerank)
    monkeypatch.setattr(pipeline, "get_chunk_texts", fake_get_chunk_texts)
    monkeypatch.setattr(pipeline, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(pipeline, "verify_citations", fake_verify_citations)
    monkeypatch.setattr(pipeline, "judge_answer", fake_judge_answer)
    monkeypatch.setattr(pipeline, "get_cached_result", fake_get_cached_result)
    monkeypatch.setattr(pipeline, "save_cached_result", fake_save_cached_result)


def test_run_eval_skips_unreviewed_questions(monkeypatch):
    reviewed = GoldenQuestion(
        id="q1", question="q", relevant_chunk_ids=["a"], reference_notes="notes", reviewed=True
    )
    unreviewed = GoldenQuestion(
        id="q2", question="q", relevant_chunk_ids=["b"], reference_notes="notes", reviewed=False
    )
    call_counts, answered = {}, []
    _patch_pipeline(monkeypatch, call_counts, answered)

    settings = Settings(anthropic_api_key="placeholder")

    result = run_eval(
        [reviewed, unreviewed], client=object(), bm25_dir=Path("unused"),
        vector_db_path=Path("unused"), settings=settings,
    )

    assert answered == ["q"]  # only the reviewed question was answered
    assert len(result.results) == 1
    assert result.correctness_rate == 1.0


def test_run_eval_retrieves_and_reranks_only_once_per_question(monkeypatch):
    question = GoldenQuestion(
        id="q1", question="q", relevant_chunk_ids=["a"], reference_notes="notes", reviewed=True
    )
    call_counts, answered = {}, []
    _patch_pipeline(monkeypatch, call_counts, answered)

    settings = Settings(anthropic_api_key="placeholder")

    run_eval(
        [question], client=object(), bm25_dir=Path("unused"),
        vector_db_path=Path("unused"), settings=settings,
    )

    # Retrieval metrics and answer generation must share one retrieve+rerank pass --
    # rerank alone measures ~5.3s/query on the real corpus (BUGS.md), so a second
    # pass per question would double this harness's cost for no correctness gain.
    assert call_counts == {"retrieve": 1, "rerank": 1}
