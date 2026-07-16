from eval.baseline import compare_to_baseline, load_latest_baseline, save_baseline
from eval.schema import EvalRunResult


def _run_result(correctness_rate: float) -> EvalRunResult:
    return EvalRunResult(
        git_commit_sha="abc123", generation_prompt_version="answer_v1",
        citations_prompt_version="verify_v1", timestamp="2026-07-14T00:00:00Z",
        results=[], mean_recall_at_k=1.0, mean_mrr=1.0, mean_ndcg=1.0,
        mean_coverage=1.0, low_confidence_rate=0.0,
        correctness_rate=correctness_rate, completeness_rate=1.0,
    )


def test_save_and_load_latest_baseline_round_trips(tmp_path):
    save_baseline(_run_result(0.9), tmp_path)

    loaded = load_latest_baseline(tmp_path)

    assert loaded.correctness_rate == 0.9


def test_load_latest_baseline_returns_none_when_empty(tmp_path):
    assert load_latest_baseline(tmp_path) is None


def test_compare_to_baseline_passes_within_tolerance():
    current = _run_result(0.85)
    baseline = _run_result(0.9)

    comparison = compare_to_baseline(current, baseline, tolerance=0.1)

    assert comparison["correctness_rate"] is True  # 0.85 >= 0.9 - 0.1


def test_compare_to_baseline_fails_beyond_tolerance():
    current = _run_result(0.5)
    baseline = _run_result(0.9)

    comparison = compare_to_baseline(current, baseline, tolerance=0.1)

    assert comparison["correctness_rate"] is False  # 0.5 < 0.9 - 0.1


def test_compare_to_baseline_skips_fields_none_on_either_side():
    current = EvalRunResult(
        git_commit_sha="cur", generation_prompt_version=None, citations_prompt_version=None,
        timestamp="t", retrieval_only=True, results=[],
        mean_recall_at_k=0.9, mean_mrr=0.9, mean_ndcg=0.9,
        mean_coverage=None, low_confidence_rate=None, correctness_rate=None, completeness_rate=None,
    )
    baseline = _run_result(0.9)  # a full run -- has real values for every field

    comparison = compare_to_baseline(current, baseline, tolerance=0.1)

    assert set(comparison) == {"mean_recall_at_k", "mean_mrr", "mean_ndcg"}
    assert all(comparison.values())
