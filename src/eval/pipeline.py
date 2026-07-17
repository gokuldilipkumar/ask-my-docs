import subprocess
from datetime import datetime, timezone
from pathlib import Path

from citations.prompt import PROMPT_VERSION as CITATIONS_PROMPT_VERSION
from citations.verify import verify_citations
from config.settings import Settings
from eval.cache import config_hash, get_cached_result, save_cached_result
from eval.judge import judge_answer
from eval.retrieval_metrics import mrr, ndcg, recall_at_k
from eval.schema import EvalResult, EvalRunResult, GoldenQuestion
from generate.client import generate_answer
from generate.prompt import PROMPT_VERSION as GENERATION_PROMPT_VERSION
from ingest.vector_index import get_chunk_texts
from observability.context import ObservabilityContext
from observability.langfuse_tracer import get_tracer
from rerank.cross_encoder import rerank
from retrieval.hybrid import hybrid_retrieve


def _git_commit_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _evaluate_one(
    question: GoldenQuestion, client, bm25_dir: Path, vector_db_path: Path, settings: Settings,
    observability: ObservabilityContext, retrieval_only: bool = False,
) -> EvalResult:
    # Wraps the whole per-question call chain in one parent span -- same fix as
    # citations/pipeline.py's answer_with_verified_citations: without it, each of this
    # question's real API-touching spans (retrieve/rerank/generate/verify) became its
    # own separate root trace instead of nesting under one trace per question.
    with observability.tracer.span(f"eval.question.{question.id}"):
        top_n_ids = hybrid_retrieve(
            bm25_dir, vector_db_path, question.question, settings.retrieval, observability=observability
        )
        texts = get_chunk_texts(vector_db_path, top_n_ids) if top_n_ids else {}
        reranked_ids = rerank(
            question.question, [(cid, texts[cid]) for cid in top_n_ids], settings.rerank, observability=observability
        )
        relevant = set(question.relevant_chunk_ids)

        retrieval_metrics = dict(
            question_id=question.id,
            recall_at_k=recall_at_k(reranked_ids, relevant, settings.eval.retrieval_k),
            mrr=mrr(reranked_ids, relevant),
            ndcg=ndcg(reranked_ids, relevant, settings.eval.retrieval_k),
        )
        if retrieval_only:
            return EvalResult(**retrieval_metrics)

        # Reuses the retrieve+rerank pass above for generation instead of calling
        # answer_with_verified_citations (which would retrieve+rerank again internally) --
        # rerank alone costs ~5.3s/query on the real corpus (BUGS.md), and this harness is
        # what Block 8 wires into CI, so a second pass per question is not free.
        answer = generate_answer(
            client, question.question, [(cid, texts[cid]) for cid in reranked_ids], settings.generation,
            observability=observability,
        )
        verified = verify_citations(
            client, question.question, answer, texts, settings.citations, observability=observability
        )
        judgment = judge_answer(
            client, question.question, verified.answer_text, question.reference_notes, settings.eval,
            observability_config=observability.config,
        )

        return EvalResult(
            **retrieval_metrics,
            coverage=verified.coverage,
            low_confidence=verified.low_confidence,
            correct=judgment.correct,
            complete=judgment.complete,
        )


def run_eval(
    golden_questions: list[GoldenQuestion], client, bm25_dir: Path, vector_db_path: Path, settings: Settings,
    retrieval_only: bool = False,
) -> EvalRunResult:
    cache_path = Path(settings.eval.cache_path)
    cfg_hash = config_hash(settings)
    observability = ObservabilityContext(tracer=get_tracer(settings), config=settings.observability)
    results: list[EvalResult] = []

    for question in golden_questions:
        if not question.reviewed:
            continue
        # The cache exists to avoid re-spending on paid API calls (design doc) --
        # retrieval_only makes none, so caching it would only add the risk of a
        # full-run cache entry being misread by a retrieval_only reader (or vice
        # versa) with no mode component in the key to catch the mismatch.
        if retrieval_only:
            results.append(_evaluate_one(question, client, bm25_dir, vector_db_path, settings, observability, True))
            continue
        cached = get_cached_result(cache_path, question.id, cfg_hash)
        if cached is not None:
            results.append(cached)
            continue
        result = _evaluate_one(question, client, bm25_dir, vector_db_path, settings, observability)
        save_cached_result(cache_path, question.id, cfg_hash, result)
        results.append(result)

    n = len(results) or 1

    def _mean_or_none(attr: str) -> float | None:
        return None if retrieval_only else sum(getattr(r, attr) for r in results) / n

    return EvalRunResult(
        git_commit_sha=_git_commit_sha(),
        generation_prompt_version=None if retrieval_only else GENERATION_PROMPT_VERSION,
        citations_prompt_version=None if retrieval_only else CITATIONS_PROMPT_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        retrieval_only=retrieval_only,
        results=results,
        mean_recall_at_k=sum(r.recall_at_k for r in results) / n,
        mean_mrr=sum(r.mrr for r in results) / n,
        mean_ndcg=sum(r.ndcg for r in results) / n,
        mean_coverage=_mean_or_none("coverage"),
        low_confidence_rate=_mean_or_none("low_confidence"),
        correctness_rate=_mean_or_none("correct"),
        completeness_rate=_mean_or_none("complete"),
    )
