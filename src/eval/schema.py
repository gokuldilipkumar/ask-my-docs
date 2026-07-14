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
    coverage: float
    low_confidence: bool
    correct: bool
    complete: bool


class EvalRunResult(BaseModel):
    git_commit_sha: str
    generation_prompt_version: str
    citations_prompt_version: str
    timestamp: str
    results: list[EvalResult]
    mean_recall_at_k: float
    mean_mrr: float
    mean_ndcg: float
    mean_coverage: float
    low_confidence_rate: float
    correctness_rate: float
    completeness_rate: float


def load_golden_questions(path: Path) -> list[GoldenQuestion]:
    raw = yaml.safe_load(path.read_text())
    return [GoldenQuestion(**item) for item in raw]
