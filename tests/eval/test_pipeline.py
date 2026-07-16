from pathlib import Path

from config.settings import Settings
from eval import pipeline
from eval.pipeline import run_eval
from eval.schema import GoldenQuestion


def _patch_pipeline(monkeypatch, call_counts, answered):
    def fake_hybrid_retrieve(bm25_dir, vector_db_path, question, config, observability=None):
        call_counts["retrieve"] = call_counts.get("retrieve", 0) + 1
        call_counts["retrieve_observability"] = observability
        return ["a"]

    def fake_rerank(question, candidates, config, observability=None):
        call_counts["rerank"] = call_counts.get("rerank", 0) + 1
        call_counts["rerank_observability"] = observability
        return [cid for cid, _ in candidates]

    def fake_get_chunk_texts(vector_db_path, ids):
        return {cid: "text" for cid in ids}

    def fake_generate_answer(client, question, chunks, config, observability=None):
        answered.append(question)
        call_counts["generate_observability"] = observability

        class FakeAnswer:
            answer_text = "answer"
            citations = ["a"]

        return FakeAnswer()

    def fake_verify_citations(client, question, answer, chunk_texts, config, observability=None):
        call_counts["verify_observability"] = observability

        class FakeVerified:
            answer_text = answer.answer_text
            citations = answer.citations
            coverage = 1.0
            low_confidence = False

        return FakeVerified()

    def fake_judge_answer(client, question, answer_text, reference_notes, config, observability_config=None):
        call_counts["judge_observability_config"] = observability_config

        class FakeJudgment:
            correct = True
            complete = True

        return FakeJudgment()

    def fake_get_cached_result(cache_path, question_id, cfg_hash):
        call_counts["cache_get"] = call_counts.get("cache_get", 0) + 1
        return None

    def fake_save_cached_result(cache_path, question_id, cfg_hash, result):
        call_counts["cache_save"] = call_counts.get("cache_save", 0) + 1

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
    assert call_counts["retrieve"] == 1
    assert call_counts["rerank"] == 1


def test_run_eval_passes_observability_config_to_judge_answer(monkeypatch):
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

    # judge_answer spends real money on every eval run -- it must be given the real
    # ObservabilityConfig so its cost lands in the daily running total, not silently
    # dropped because the caller forgot to pass it through.
    assert call_counts["judge_observability_config"] is settings.observability


def test_run_eval_passes_a_cost_tracking_observability_context_to_generation_and_verification(monkeypatch):
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

    # generate_answer and verify_citations both hit the real Anthropic API during an
    # eval run -- omitting observability here (as this pipeline did before this fix)
    # meant their real cost silently never counted against daily_cost_cap_usd, even
    # though judge_answer's cost was tracked. Both must receive a context carrying
    # the real ObservabilityConfig so report_usage actually fires.
    for key in ("generate_observability", "verify_observability"):
        observability = call_counts[key]
        assert observability is not None
        assert observability.config is settings.observability


def test_run_eval_retrieval_only_skips_generation_and_the_cache(monkeypatch):
    question = GoldenQuestion(
        id="q1", question="q", relevant_chunk_ids=["a"], reference_notes="notes", reviewed=True
    )
    call_counts, answered = {}, []
    _patch_pipeline(monkeypatch, call_counts, answered)

    settings = Settings(anthropic_api_key="placeholder")

    result = run_eval(
        [question], client=object(), bm25_dir=Path("unused"),
        vector_db_path=Path("unused"), settings=settings, retrieval_only=True,
    )

    assert answered == []  # generate_answer never called
    assert "judge_observability_config" not in call_counts  # judge_answer never called
    assert "cache_get" not in call_counts  # cache never touched in retrieval_only mode
    assert "cache_save" not in call_counts
    assert result.retrieval_only is True
    assert result.results[0].correct is None
    assert result.results[0].coverage is None
    assert result.correctness_rate is None
    assert result.completeness_rate is None
    assert result.mean_coverage is None
    assert result.low_confidence_rate is None
    assert result.generation_prompt_version is None
    assert result.citations_prompt_version is None
    assert result.mean_recall_at_k == 1.0  # retrieval metrics still computed
    assert result.mean_mrr == 1.0
    assert result.mean_ndcg == 1.0


def test_run_eval_full_mode_still_uses_the_cache(monkeypatch):
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

    assert call_counts["cache_get"] == 1
    assert call_counts["cache_save"] == 1
