from pathlib import Path

import yaml
from pydantic import BaseModel


class GoldenQuestion(BaseModel):
    id: str
    question: str
    relevant_chunk_ids: list[str] = []
    reference_notes: str = ""
    auto_generated: bool = False
    reviewed: bool = False


class EvalResult(BaseModel):
    question_id: str
    recall_at_k: float
    mrr: float
    ndcg: float
    # None in retrieval_only mode -- distinct from "computed and failed", not a sentinel.
    coverage: float | None = None
    low_confidence: bool | None = None
    correct: bool | None = None
    complete: bool | None = None


class EvalRunResult(BaseModel):
    git_commit_sha: str
    generation_prompt_version: str | None = None
    citations_prompt_version: str | None = None
    timestamp: str
    retrieval_only: bool = False
    results: list[EvalResult]
    mean_recall_at_k: float
    mean_mrr: float
    mean_ndcg: float
    mean_coverage: float | None = None
    low_confidence_rate: float | None = None
    correctness_rate: float | None = None
    completeness_rate: float | None = None


def load_golden_questions(path: Path) -> list[GoldenQuestion]:
    raw = yaml.safe_load(path.read_text())
    return [GoldenQuestion(**item) for item in raw]
