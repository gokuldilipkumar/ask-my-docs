from datetime import datetime, timezone
from pathlib import Path

from eval.schema import EvalRunResult

_METRIC_FIELDS = [
    "mean_recall_at_k", "mean_mrr", "mean_ndcg", "mean_coverage",
    "correctness_rate", "completeness_rate",
]


def save_baseline(run_result: EvalRunResult, baseline_dir: Path) -> Path:
    baseline_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = baseline_dir / f"{ts}_{run_result.git_commit_sha[:8]}.json"
    path.write_text(run_result.model_dump_json(indent=2))
    return path


def load_latest_baseline(baseline_dir: Path) -> EvalRunResult | None:
    if not baseline_dir.exists():
        return None
    files = sorted(baseline_dir.glob("*.json"))
    if not files:
        return None
    return EvalRunResult.model_validate_json(files[-1].read_text())


def compare_to_baseline(
    current: EvalRunResult, baseline: EvalRunResult, tolerance: float
) -> dict[str, bool]:
    return {
        field: getattr(current, field) >= getattr(baseline, field) - tolerance
        for field in _METRIC_FIELDS
    }
