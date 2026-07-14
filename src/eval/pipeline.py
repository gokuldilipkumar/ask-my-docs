import subprocess
from datetime import datetime, timezone
from pathlib import Path

from citations.pipeline import answer_with_verified_citations
from citations.prompt import PROMPT_VERSION as CITATIONS_PROMPT_VERSION
from config.settings import Settings
from eval.cache import config_hash, get_cached_result, save_cached_result
from eval.judge import judge_answer
from eval.retrieval_metrics import mrr, ndcg, recall_at_k
from eval.schema import EvalResult, EvalRunResult, GoldenQuestion
from generate.prompt import PROMPT_VERSION as GENERATION_PROMPT_VERSION
from ingest.vector_index import get_chunk_texts
from rerank.cross_encoder import rerank
from retrieval.hybrid import hybrid_retrieve


def _git_commit_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _evaluate_one(
    question: GoldenQuestion, client, bm25_dir: Path, vector_db_path: Path, settings: Settings
) -> EvalResult:
    top_n_ids = hybrid_retrieve(bm25_dir, vector_db_path, question.question, settings.retrieval)
    texts = get_chunk_texts(vector_db_path, top_n_ids) if top_n_ids else {}
    reranked_ids = rerank(question.question, [(cid, texts[cid]) for cid in top_n_ids], settings.rerank)
    relevant = set(question.relevant_chunk_ids)

    verified = answer_with_verified_citations(
        question.question, client, bm25_dir, vector_db_path, settings
    )
    judgment = judge_answer(
        client, question.question, verified.answer_text, question.reference_notes, settings.eval
    )

    return EvalResult(
        question_id=question.id,
        recall_at_k=recall_at_k(reranked_ids, relevant, settings.eval.retrieval_k),
        mrr=mrr(reranked_ids, relevant),
        ndcg=ndcg(reranked_ids, relevant, settings.eval.retrieval_k),
        coverage=verified.coverage,
        low_confidence=verified.low_confidence,
        correct=judgment.correct,
        complete=judgment.complete,
    )


def run_eval(
    golden_questions: list[GoldenQuestion], client, bm25_dir: Path, vector_db_path: Path, settings: Settings
) -> EvalRunResult:
    cache_path = Path(settings.eval.cache_path)
    cfg_hash = config_hash(settings)
    results: list[EvalResult] = []

    for question in golden_questions:
        if not question.reviewed:
            continue
        cached = get_cached_result(cache_path, question.id, cfg_hash)
        if cached is not None:
            results.append(cached)
            continue
        result = _evaluate_one(question, client, bm25_dir, vector_db_path, settings)
        save_cached_result(cache_path, question.id, cfg_hash, result)
        results.append(result)

    n = len(results) or 1
    return EvalRunResult(
        git_commit_sha=_git_commit_sha(),
        generation_prompt_version=GENERATION_PROMPT_VERSION,
        citations_prompt_version=CITATIONS_PROMPT_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        results=results,
        mean_recall_at_k=sum(r.recall_at_k for r in results) / n,
        mean_mrr=sum(r.mrr for r in results) / n,
        mean_ndcg=sum(r.ndcg for r in results) / n,
        mean_coverage=sum(r.coverage for r in results) / n,
        low_confidence_rate=sum(r.low_confidence for r in results) / n,
        correctness_rate=sum(r.correct for r in results) / n,
        completeness_rate=sum(r.complete for r in results) / n,
    )
