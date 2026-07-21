from typer.testing import CliRunner

from app.main import app
from eval.schema import EvalRunResult

runner = CliRunner()


def _run_result(**overrides) -> EvalRunResult:
    defaults = dict(
        git_commit_sha="cur", generation_prompt_version="answer_v1", citations_prompt_version="verify_v1",
        timestamp="t", retrieval_only=False, results=[],
        mean_recall_at_k=0.9, mean_mrr=0.9, mean_ndcg=0.9,
        mean_coverage=1.0, low_confidence_rate=0.0, correctness_rate=0.8, completeness_rate=0.6,
    )
    defaults.update(overrides)
    return EvalRunResult(**defaults)


def test_eval_command_passes_and_exits_zero(monkeypatch):
    from app import main as app_main

    current = _run_result()
    baseline = _run_result(git_commit_sha="base")
    monkeypatch.setattr(app_main, "run_eval", lambda *a, **k: current)
    monkeypatch.setattr(app_main, "load_latest_baseline", lambda *a: baseline)
    monkeypatch.setattr(app_main, "load_golden_questions", lambda *a: [])
    monkeypatch.setattr(app_main, "format_daily_cost", lambda *a: "$0.0000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = runner.invoke(app, ["eval"])

    assert result.exit_code == 0
    assert "mean_recall_at_k: PASS" in result.stdout


def test_eval_command_exits_nonzero_on_regression(monkeypatch):
    from app import main as app_main

    regressed = _run_result(mean_recall_at_k=0.3, mean_mrr=0.3, mean_ndcg=0.3)  # deliberately far below baseline
    good_baseline = _run_result(git_commit_sha="base")
    monkeypatch.setattr(app_main, "run_eval", lambda *a, **k: regressed)
    monkeypatch.setattr(app_main, "load_latest_baseline", lambda *a: good_baseline)
    monkeypatch.setattr(app_main, "load_golden_questions", lambda *a: [])
    monkeypatch.setattr(app_main, "format_daily_cost", lambda *a: "$0.0000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = runner.invoke(app, ["eval"])

    assert result.exit_code == 1
    assert "mean_recall_at_k: FAIL" in result.stdout


def test_eval_command_reports_no_baseline_and_exits_zero(monkeypatch):
    from app import main as app_main

    monkeypatch.setattr(app_main, "run_eval", lambda *a, **k: _run_result())
    monkeypatch.setattr(app_main, "load_latest_baseline", lambda *a: None)
    monkeypatch.setattr(app_main, "load_golden_questions", lambda *a: [])
    monkeypatch.setattr(app_main, "format_daily_cost", lambda *a: "$0.0000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = runner.invoke(app, ["eval"])

    assert result.exit_code == 0
    assert "No baseline found" in result.stdout


def test_eval_command_saves_baseline_when_requested(monkeypatch):
    from app import main as app_main

    saved = []
    monkeypatch.setattr(app_main, "run_eval", lambda *a, **k: _run_result())
    monkeypatch.setattr(app_main, "load_latest_baseline", lambda *a: None)
    monkeypatch.setattr(app_main, "load_golden_questions", lambda *a: [])
    monkeypatch.setattr(app_main, "format_daily_cost", lambda *a: "$0.0000")
    monkeypatch.setattr(app_main, "save_baseline_run", lambda result, path: saved.append((result, path)) or "saved.json")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = runner.invoke(app, ["eval", "--save-baseline"])

    assert result.exit_code == 0
    assert len(saved) == 1
    assert "Saved baseline" in result.stdout


def test_eval_command_refuses_to_save_baseline_in_retrieval_only_mode(monkeypatch):
    from app import main as app_main

    retrieval_only_result = _run_result(
        retrieval_only=True, generation_prompt_version=None, citations_prompt_version=None,
        mean_coverage=None, low_confidence_rate=None, correctness_rate=None, completeness_rate=None,
    )
    saved = []
    monkeypatch.setattr(app_main, "run_eval", lambda *a, **k: retrieval_only_result)
    monkeypatch.setattr(app_main, "load_latest_baseline", lambda *a: None)
    monkeypatch.setattr(app_main, "load_golden_questions", lambda *a: [])
    monkeypatch.setattr(app_main, "format_daily_cost", lambda *a: "$0.0000")
    monkeypatch.setattr(app_main, "save_baseline_run", lambda result, path: saved.append((result, path)) or "saved.json")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = runner.invoke(app, ["eval", "--retrieval-only", "--save-baseline"])

    assert result.exit_code == 0
    assert saved == []
    assert "Skipping baseline save" in result.stdout


def test_eval_command_passes_retrieval_only_flag_through_to_run_eval(monkeypatch):
    from app import main as app_main

    captured = {}

    def fake_run_eval(questions, client, bm25_dir, vector_db_path, settings, retrieval_only=False):
        captured["retrieval_only"] = retrieval_only
        return _run_result(retrieval_only=retrieval_only)

    monkeypatch.setattr(app_main, "run_eval", fake_run_eval)
    monkeypatch.setattr(app_main, "load_latest_baseline", lambda *a: None)
    monkeypatch.setattr(app_main, "load_golden_questions", lambda *a: [])
    monkeypatch.setattr(app_main, "format_daily_cost", lambda *a: "$0.0000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    runner.invoke(app, ["eval", "--retrieval-only"])

    assert captured["retrieval_only"] is True
