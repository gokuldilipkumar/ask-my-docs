import hashlib
import json
import sqlite3
from pathlib import Path

from config.settings import Settings
from eval.schema import EvalResult

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS eval_cache (
    question_id TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    PRIMARY KEY (question_id, config_hash)
)
"""


def config_hash(settings: Settings) -> str:
    relevant = {
        "retrieval": settings.retrieval.model_dump(),
        "rerank": settings.rerank.model_dump(),
        "generation": settings.generation.model_dump(),
        "citations": settings.citations.model_dump(),
        "eval": settings.eval.model_dump(),
    }
    payload = json.dumps(relevant, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _connect(cache_path: Path) -> sqlite3.Connection:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cache_path)
    conn.execute(_CREATE_TABLE)
    return conn


def get_cached_result(cache_path: Path, question_id: str, cfg_hash: str) -> EvalResult | None:
    with _connect(cache_path) as conn:
        row = conn.execute(
            "SELECT result_json FROM eval_cache WHERE question_id = ? AND config_hash = ?",
            (question_id, cfg_hash),
        ).fetchone()
    return EvalResult.model_validate_json(row[0]) if row else None


def save_cached_result(cache_path: Path, question_id: str, cfg_hash: str, result: EvalResult) -> None:
    with _connect(cache_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO eval_cache (question_id, config_hash, result_json) VALUES (?, ?, ?)",
            (question_id, cfg_hash, result.model_dump_json()),
        )
