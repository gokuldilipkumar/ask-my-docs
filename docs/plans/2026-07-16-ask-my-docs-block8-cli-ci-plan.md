# Block 8 Implementation Plan — CLI Completion + CI

**Date**: 2026-07-16
**Parent plan**: `2026-07-11-ask-my-docs-implementation-plan.md` (Block 8 sketch)
**Design doc**: `2026-07-10-ask-my-docs-design.md`

## Header

- **Goal**: Complete the `app/main.py` CLI surface with `query` (ask a question, get a verified-cited answer) and `eval` (run the golden-dataset harness, compare to baseline, exit non-zero on regression) commands; wire `run_eval`/`compare_to_baseline` into two GitHub Actions workflows — `cheap-gate.yml` (zero-API-cost retrieval metrics on every push) and `nightly-eval.yml` (full judge-based metrics on a schedule/manual trigger) — and push this repository to a real GitHub remote so CI actually runs and is visible.
- **Architecture**: `app/main.py` gains two `typer` commands reusing existing orchestrators (`answer_with_verified_citations` for `query`, `run_eval`/`compare_to_baseline`/`save_baseline`/`load_latest_baseline` for `eval`) — no new pipeline logic, only CLI wiring, except one real gap: `run_eval`/`_evaluate_one` currently always call the real Anthropic API (generation + citation verification + judge), so there is no way today to run *only* the free retrieval metrics the design doc's "cheap gate" needs. This block adds a `retrieval_only` mode to close that gap. `.github/workflows/` gets two YAML files calling the `eval` CLI command with different flags/secrets/triggers.
- **Design patterns**: Same additive-optional pattern Block 7 established (`retrieval_only: bool = False`) rather than a parallel `run_retrieval_eval` function — one code path, one place the retrieve→rerank→metrics logic can drift out of sync with the full path. CI index provisioning uses a committed artifact, not a rebuild-on-every-run cache, per Decision 2 below.
- **Tech stack**: `typer` (already used by `ingest`), GitHub Actions (`.github/workflows/*.yml`), `gh` CLI for one-time repo creation. No new Python dependencies.

## Conventions Check

- **Reuse audit**: `answer_with_verified_citations(question, client, bm25_dir, vector_db_path, settings) -> VerifiedAnswer` (`src/citations/pipeline.py`) already does everything `query` needs — construct an `anthropic.Anthropic` client and call it, no new orchestration. `run_eval`/`compare_to_baseline`/`save_baseline`/`load_latest_baseline` (`src/eval/pipeline.py`, `src/eval/baseline.py`) already do everything `eval` needs *except* a cheap, no-API-cost mode — that's this block's one real piece of new logic, not new orchestration machinery. `get_daily_total` (`src/observability/daily_cost.py`) already exists for the "print daily cost" behavior both commands add — this also closes the Block 7 `BUGS.md` item "no CLI command surfaces the daily running cost total yet."
- **Additive-Parameter Reach Audit** (new `plan.md` checklist item, added at this block's own `/kaizen`): `run_eval` gains `retrieval_only: bool = False`. Its only real caller today is the new `eval` CLI command being built in this same block (Chunk 8.3) — there is no pre-existing caller to audit for reach, unlike Block 7's observability parameter. Noted explicitly so this doesn't silently become the next block's version of the same gap.
- **Composition Cost Audit**: `retrieval_only` mode still calls `hybrid_retrieve` + `get_chunk_texts` + `rerank` (rerank needs real chunk text to score candidates, even though its output feeds pure-CPU metrics) — no new expensive step, and it *skips* the three real API calls (`generate_answer`, `verify_citations`, `judge_answer`), making it strictly cheaper than a full run, not a parallel duplicate of it.
- **Test style**: pytest, `typer.testing.CliRunner`, monkeypatching the pipeline functions `app.main` imports (same isolation pattern as `tests/app/test_ingest_command.py`'s `isolated_config` fixture) for fast CLI-wiring tests; one `live_api`-marked test per command for genuine end-to-end confidence, mirroring every prior block's convention.
- **Config-isolation check**: `query`/`eval` both take an `--index` option (default `Path("data/index")`, matching `ingest`'s own `--out` convention) rather than a new config key — index location is a deployment concern, not a corpus-tuning constant.

### Decisions made at plan time (not deferred to build)

1. **GitHub remote created and pushed this block** (user's explicit choice, 2026-07-16, over "author YAML only"). CI workflows that never run are not verifiable and don't serve the portfolio/hiring-manager audience CLAUDE.md names. Exact repo name/visibility (public, matching the portfolio framing) confirmed interactively at Chunk 8.0's build time, not hardcoded here.
2. **`data/index/` (the built BM25 + LanceDB indexes, ~7.3MB) is committed to git** (user's explicit choice, over rebuild-in-CI via a cached PDF download). Rejected: downloading the 273MB PDF and re-running `ingest` in CI, cached by a corpus/code hash — adds cache-invalidation design, a cold-start first run, and a dependency on an external government URL staying reachable, for a corpus that isn't actually changing. `.gitignore`'s blanket `data/` exclusion is narrowed to exclude everything *except* `data/index/` (sqlite caches — `daily_cost.sqlite3`, `eval_cache.sqlite3` — stay ignored, they're per-machine/per-run state, not build artifacts).
3. **`serve` is out of scope for this block** (user's explicit choice). `query`/`eval` are what CI and a portfolio demo actually need; a long-running server has its own framework/auth/deployment design questions better scoped separately if ever needed.
4. **`retrieval_only` is a parameter on the existing `run_eval`/`_evaluate_one`, not a separate function.** Rejected: a parallel `run_retrieval_eval` — the retrieve→rerank→metrics logic (three function calls, two config objects) would exist in two places that must be kept in sync by hand. The additive-optional-parameter shape already proved itself in Block 7.
5. **`EvalResult`'s answer-quality fields (`coverage`, `low_confidence`, `correct`, `complete`) become `Optional`, defaulting to `None` when `retrieval_only=True`**, rather than sentinel values (`0.0`/`False`). Rejected: sentinels — a `retrieval_only` run's `correct=False` would be indistinguishable from a full run's genuine judge failure in any report or downstream code that doesn't also check a mode flag; `None` makes "this was never computed" structurally different from "this was computed and failed," matching this project's established fail-loud-over-silent-degrade preference. `EvalRunResult` gains a `retrieval_only: bool` field so a stored baseline or CI log is self-describing.
6. **`compare_to_baseline` skips a metric field in its comparison when either side's value is `None`**, rather than requiring both `EvalRunResult`s to be full runs. This lets `cheap-gate.yml` compare a `retrieval_only` run against the *same* baseline file `nightly-eval.yml` writes (a full run) — no second baseline store, no duplicated "latest baseline" concept. The 3 retrieval fields (`mean_recall_at_k`/`mean_mrr`/`mean_ndcg`) are always present on both, so the cheap gate always has something real to compare.
7. **`run_eval` skips the sqlite response cache entirely when `retrieval_only=True`** (no read, no write) rather than adding `retrieval_only` to the cache key. Rejected: extending `config_hash` — the cache exists to avoid re-spending on *paid* API calls during eval-harness debugging (per the design doc); a `retrieval_only` run makes zero paid calls, so caching it saves local BM25/embedding/rerank compute at the cost of a real correctness risk (a `(question_id, config_hash)` cache entry written by a full run, if ever read back by a `retrieval_only` run or vice versa without a mode component in the key, would silently return the wrong shape's data). Skipping the cache removes that risk entirely for a mode where caching's own justification doesn't apply.
8. **CI's fast unit-test suite and `cheap-gate.yml`'s retrieval-only eval both need `ANTHROPIC_API_KEY` present as a real environment variable (even though neither spends money)**, because `Settings.anthropic_api_key` has no default and pydantic-settings will fail to construct `Settings()` without it. `cheap-gate.yml` sets a plain (non-secret) placeholder env var directly in the workflow YAML, with a comment explaining why a fake value is safe here specifically. `nightly-eval.yml` uses a real `ANTHROPIC_API_KEY` GitHub Actions *secret*, since it makes real paid calls.

## Block 8: CLI Completion + CI

**Success criteria**

- [ ] `query` CLI command answers a question end-to-end via `answer_with_verified_citations` and prints the answer, citations, coverage/low-confidence flag, and running daily cost.
- [ ] `run_eval`/`_evaluate_one` support a `retrieval_only` mode computing only `recall_at_k`/`mrr`/`ndcg` (pure CPU, zero Anthropic API calls); `EvalRunResult.retrieval_only` records which mode produced it; the sqlite response cache is bypassed in this mode.
- [ ] `compare_to_baseline` skips metric fields that are `None` on either side, so a `retrieval_only` current run can be compared against a full-run baseline.
- [ ] `eval` CLI command runs the harness (full or `--retrieval-only`), prints a per-metric PASS/FAIL vs. the latest baseline, exits non-zero if any compared metric fails its tolerance band, optionally saves a new baseline (`--save-baseline`, refused in `--retrieval-only` mode), and prints the running daily cost.
- [ ] A deliberately-regressed `EvalRunResult` fixture proves the `eval` command's exit code actually goes non-zero (design doc acceptance criterion: "a deliberately bad prompt/config change fails the CI gate").
- [ ] `.github/workflows/cheap-gate.yml` runs the fast test suite + `eval --retrieval-only` on every push, fails the job if any retrieval metric regresses beyond tolerance, spends zero real API dollars.
- [ ] `.github/workflows/nightly-eval.yml` runs the full `eval` (all metrics, real API cost) on a daily schedule + manual `workflow_dispatch`, using a real `ANTHROPIC_API_KEY` secret, and saves a new baseline on success.
- [ ] Repository pushed to a real GitHub remote; both workflows verified actually running (not just YAML sitting unexecuted) — `cheap-gate.yml` on the push itself, `nightly-eval.yml` via a manual `workflow_dispatch` trigger.
- [ ] `data/index/` is tracked in git (~7.3MB); `.gitignore` still excludes the source PDF and per-machine sqlite state.

---

### Chunk 8.0 — Prerequisite: GitHub remote + committed index (no TDD, infra setup)

Not a RED-GREEN-COMMIT chunk — matches Block 7's Chunk 7.0 precedent for one-time environment/infra prerequisites.

1. Confirm `gh auth status` is authenticated (if not, ask the user to run `! gh auth login` interactively — cannot be scripted).
2. Ask the user for repo name (default `ask-my-docs`, matching `pyproject.toml`'s `[project].name`) and confirm public visibility (portfolio framing implies public).
3. Re-run `ingest` cleanly into a fresh `data/index/` (deletes the current directory first) so the committed LanceDB table has no orphaned multi-version `.lance`/`_transactions`/`_versions` cruft from this project's iterative re-ingestion history (currently 3 stale `.lance` data files from 3 different ingests, only the latest live).
4. Edit `.gitignore`: replace the blanket `data/` line with:
   ```
   # Ingestion artifacts (regenerable from the PDF) except the built index,
   # which CI needs and is small enough (~7MB) to commit directly.
   data/*
   !data/index/
   !data/index/**
   ```
   Remove the now-redundant `*.lance/` line (it would re-exclude `data/index/lancedb/chunks.lance/`, defeating the negation above).
5. `git add .gitignore data/index && git commit -m "[Infra] Repo: commit built index for CI, narrow data/ gitignore"`.
6. `gh repo create <name> --public --source=. --remote=origin` (or equivalent explicit `git remote add origin` if the repo already exists on GitHub).
7. `git push -u origin master` (confirm branch name — this repo's default is `master`, not `main`; GitHub Actions workflow `on: push` triggers work regardless of branch name, but `nightly-eval.yml`'s cron doesn't care about branch at all).

---

### Chunk 8.1 — `query` CLI command

**Files**: Modify: `src/app/main.py`. Create: `tests/app/test_query_command.py`.

**Step 1: Write failing test**
```python
import pytest
from typer.testing import CliRunner

from app.main import app

runner = CliRunner()


def test_query_command_prints_answer_citations_and_cost(monkeypatch, tmp_path):
    from app import main as app_main

    class FakeVerified:
        answer_text = "Stalls occur when the critical angle of attack is exceeded."
        citations = ["abc123"]
        coverage = 1.0
        low_confidence = False

    def fake_answer_with_verified_citations(question, client, bm25_dir, vector_db_path, settings):
        assert question == "What causes a stall?"
        return FakeVerified()

    monkeypatch.setattr(app_main, "answer_with_verified_citations", fake_answer_with_verified_citations)
    monkeypatch.setattr(app_main, "get_daily_total", lambda db_path: 0.0421)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = runner.invoke(app, ["query", "--question", "What causes a stall?"])

    assert result.exit_code == 0
    assert "Stalls occur when" in result.stdout
    assert "abc123" in result.stdout
    assert "0.0421" in result.stdout
```

**Step 2: Verify failure**: `uv run pytest tests/app/test_query_command.py -q` — fails with `AttributeError` (no `query` command registered / `answer_with_verified_citations` not imported into `app.main`).

**Step 3: Implement minimal code** (`src/app/main.py`):
```python
import anthropic

from citations.pipeline import answer_with_verified_citations
from observability.daily_cost import get_daily_total

@app.command()
def query(
    question: str = typer.Option(...),
    index: Path = typer.Option(Path("data/index")),
) -> None:
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    result = answer_with_verified_citations(question, client, index / "bm25", index / "lancedb", settings)

    typer.echo(result.answer_text)
    if result.citations:
        typer.echo(f"Citations: {', '.join(result.citations)}")
    flag = " (low confidence)" if result.low_confidence else ""
    typer.echo(f"Coverage: {result.coverage:.2f}{flag}")

    total_cost = get_daily_total(Path(settings.observability.cost_db_path))
    typer.echo(f"Daily cost so far: ${total_cost:.4f}")
```

**Step 4: Verify pass**: test green. Also add one `live_api`-marked test building a tiny real index (`build_bm25_index`/`build_vector_index` on 2-3 synthetic chunks in `tmp_path`, via the existing `make_chunk` fixture) and invoking `query` for real, asserting a non-empty answer — mirrors Block 4-6's "at least one genuine end-to-end test" convention.

**Step 5: Commit**: `git add src/app/main.py tests/app/test_query_command.py && git commit -m "[Feature] CLI: query command answers via answer_with_verified_citations"`.

---

### Chunk 8.2 — `retrieval_only` eval mode

**Files**: Modify: `src/eval/schema.py`, `src/eval/pipeline.py`, `src/eval/baseline.py`, `tests/eval/test_pipeline.py`, `tests/eval/test_baseline.py`.

**Step 1: Write failing test** (schema + orchestration + cache-bypass + comparison, as separate assertions in the existing test files):
```python
# tests/eval/test_pipeline.py
def test_run_eval_retrieval_only_skips_generation_and_the_cache(monkeypatch, tmp_path):
    question = GoldenQuestion(
        id="q1", question="q", relevant_chunk_ids=["a"], reference_notes="notes", reviewed=True
    )
    call_counts, answered = {}, []
    _patch_pipeline(monkeypatch, call_counts, answered)
    cache_calls = []
    monkeypatch.setattr(pipeline, "get_cached_result", lambda *a: cache_calls.append(("get", a)) or None)
    monkeypatch.setattr(pipeline, "save_cached_result", lambda *a: cache_calls.append(("save", a)))

    settings = Settings(anthropic_api_key="placeholder")

    result = run_eval(
        [question], client=object(), bm25_dir=Path("unused"),
        vector_db_path=Path("unused"), settings=settings, retrieval_only=True,
    )

    assert answered == []  # generate_answer never called
    assert cache_calls == []  # cache never touched in retrieval_only mode
    assert result.retrieval_only is True
    assert result.results[0].correct is None
    assert result.correctness_rate is None
    assert result.mean_recall_at_k == 1.0  # metrics still computed
```
```python
# tests/eval/test_baseline.py
def test_compare_to_baseline_skips_fields_none_on_either_side():
    current = EvalRunResult(
        git_commit_sha="abc", generation_prompt_version=None, citations_prompt_version=None,
        timestamp="t", retrieval_only=True, results=[],
        mean_recall_at_k=0.9, mean_mrr=0.9, mean_ndcg=0.9,
        mean_coverage=None, low_confidence_rate=None, correctness_rate=None, completeness_rate=None,
    )
    baseline = EvalRunResult(
        git_commit_sha="def", generation_prompt_version="answer_v1", citations_prompt_version="verify_v1",
        timestamp="t", retrieval_only=False, results=[],
        mean_recall_at_k=0.85, mean_mrr=0.85, mean_ndcg=0.85,
        mean_coverage=1.0, low_confidence_rate=0.0, correctness_rate=0.8, completeness_rate=0.6,
    )

    comparison = compare_to_baseline(current, baseline, tolerance=0.1)

    assert set(comparison) == {"mean_recall_at_k", "mean_mrr", "mean_ndcg"}
    assert all(comparison.values())
```

**Step 2: Verify failure**: both fail — `retrieval_only` isn't a parameter yet, `EvalRunResult`/`EvalResult` don't have `Optional` fields or a `retrieval_only` field, `compare_to_baseline` has no None-skip logic (would raise `TypeError` comparing `None` to a float).

**Step 3: Implement minimal code**:
- `src/eval/schema.py`: make `EvalResult.coverage`/`low_confidence`/`correct`/`complete` and `EvalRunResult.generation_prompt_version`/`citations_prompt_version`/`mean_coverage`/`low_confidence_rate`/`correctness_rate`/`completeness_rate` all `X | None = None`; add `EvalRunResult.retrieval_only: bool = False`.
- `src/eval/pipeline.py`: `_evaluate_one` and `run_eval` gain `retrieval_only: bool = False`. Inside `_evaluate_one`, compute `recall`/`mrr`/`ndcg` unconditionally, then branch: if `retrieval_only`, return an `EvalResult` with only those three fields set; otherwise proceed to `generate_answer`/`verify_citations`/`judge_answer` as today. Inside `run_eval`, skip `get_cached_result`/`save_cached_result` entirely when `retrieval_only`; compute the four answer-quality aggregate fields as `None` in that mode (helper `_mean_or_none(attr)` returning `None` if `retrieval_only` else the existing sum/n).
- `src/eval/baseline.py`: `compare_to_baseline` filters `_METRIC_FIELDS` to only fields where both `getattr(current, field)` and `getattr(baseline, field)` are not `None` before comparing.

**Step 4: Verify pass**: `uv run pytest tests/eval/ -q` green, including existing full-mode tests (backward compatible — `retrieval_only` defaults `False`, all existing assertions on concrete float/bool values unaffected).

**Step 5: Commit**: `git add src/eval/schema.py src/eval/pipeline.py src/eval/baseline.py tests/eval/test_pipeline.py tests/eval/test_baseline.py && git commit -m "[Feature] Eval: retrieval_only mode -- zero-API-cost metrics for the cheap CI gate"`.

---

### Chunk 8.3 — `eval` CLI command

**Files**: Modify: `src/app/main.py`. Create: `tests/app/test_eval_command.py`.

**Step 1: Write failing test** (three cases: passes against baseline, fails and exits non-zero on a deliberately regressed result, `--save-baseline` refused under `--retrieval-only`):
```python
def test_eval_command_exits_nonzero_on_regression(monkeypatch, tmp_path):
    from app import main as app_main

    regressed = EvalRunResult(
        git_commit_sha="cur", generation_prompt_version="answer_v1", citations_prompt_version="verify_v1",
        timestamp="t", retrieval_only=False, results=[],
        mean_recall_at_k=0.3, mean_mrr=0.3, mean_ndcg=0.3,  # deliberately far below baseline
        mean_coverage=1.0, low_confidence_rate=0.0, correctness_rate=0.8, completeness_rate=0.6,
    )
    good_baseline = EvalRunResult(
        git_commit_sha="base", generation_prompt_version="answer_v1", citations_prompt_version="verify_v1",
        timestamp="t", retrieval_only=False, results=[],
        mean_recall_at_k=0.9, mean_mrr=0.9, mean_ndcg=0.9,
        mean_coverage=1.0, low_confidence_rate=0.0, correctness_rate=0.8, completeness_rate=0.6,
    )
    monkeypatch.setattr(app_main, "run_eval", lambda *a, **k: regressed)
    monkeypatch.setattr(app_main, "load_latest_baseline", lambda *a: good_baseline)
    monkeypatch.setattr(app_main, "load_golden_questions", lambda *a: [])
    monkeypatch.setattr(app_main, "get_daily_total", lambda *a: 0.0)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = runner.invoke(app, ["eval"])

    assert result.exit_code == 1
    assert "mean_recall_at_k: FAIL" in result.stdout


def test_eval_command_refuses_to_save_baseline_in_retrieval_only_mode(monkeypatch):
    from app import main as app_main

    monkeypatch.setattr(app_main, "run_eval", lambda *a, **k: _retrieval_only_result())
    monkeypatch.setattr(app_main, "load_latest_baseline", lambda *a: None)
    monkeypatch.setattr(app_main, "load_golden_questions", lambda *a: [])
    saved = []
    monkeypatch.setattr(app_main, "save_baseline_run", lambda *a: saved.append(a))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    runner.invoke(app, ["eval", "--retrieval-only", "--save-baseline"])

    assert saved == []
```

**Step 2: Verify failure**: `eval` command doesn't exist yet.

**Step 3: Implement minimal code** (`src/app/main.py`):
```python
from eval.baseline import compare_to_baseline, load_latest_baseline
from eval.baseline import save_baseline as save_baseline_run  # avoid shadowing the --save-baseline flag name
from eval.pipeline import run_eval
from eval.schema import load_golden_questions

@app.command(name="eval")
def eval_command(
    index: Path = typer.Option(Path("data/index")),
    retrieval_only: bool = typer.Option(False, "--retrieval-only"),
    save_baseline: bool = typer.Option(False, "--save-baseline"),
) -> None:
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    questions = load_golden_questions(Path(settings.eval.golden_path))

    result = run_eval(
        questions, client, index / "bm25", index / "lancedb", settings, retrieval_only=retrieval_only
    )

    exit_code = 0
    baseline = load_latest_baseline(Path(settings.eval.baseline_dir))
    if baseline is None:
        typer.echo("No baseline found -- nothing to compare against.")
    else:
        comparison = compare_to_baseline(result, baseline, settings.eval.tolerance)
        for metric, passed in comparison.items():
            status = "PASS" if passed else "FAIL"
            typer.echo(f"{metric}: {status} (current={getattr(result, metric):.3f}, baseline={getattr(baseline, metric):.3f})")
        if not all(comparison.values()):
            exit_code = 1

    if save_baseline:
        if retrieval_only:
            typer.echo("Skipping baseline save: --retrieval-only runs must not become the tracked baseline.")
        else:
            path = save_baseline_run(result, Path(settings.eval.baseline_dir))
            typer.echo(f"Saved baseline: {path}")

    total_cost = get_daily_total(Path(settings.observability.cost_db_path))
    typer.echo(f"Daily cost so far: ${total_cost:.4f}")

    raise typer.Exit(code=exit_code)
```

**Step 4: Verify pass**: both unit tests green. Add one `live_api`-marked end-to-end test running `eval --retrieval-only` against a tiny real synthetic index (fast, zero cost) as the genuine-confidence check — a full non-`retrieval_only` live test would duplicate Block 6's own already-covered `run_eval` live coverage for real money, so this block's live test targets the CLI wiring + `retrieval_only` path specifically, not `run_eval` itself again.

**Step 5: Commit**: `git add src/app/main.py tests/app/test_eval_command.py && git commit -m "[Feature] CLI: eval command -- baseline compare, exit-code gate, retrieval_only support"`.

---

### Chunk 8.4 — `.github/workflows/cheap-gate.yml`

**Files**: Create: `.github/workflows/cheap-gate.yml`.

Not TDD (YAML, not Python) — verified by Chunk 8.6's real push, and locally beforehand via `act` if available, or by careful manual trace against `uv`'s actual CLI surface.

```yaml
name: cheap-gate

on: [push, pull_request]

jobs:
  test-and-retrieval-eval:
    runs-on: ubuntu-latest
    env:
      # Settings.anthropic_api_key has no default and is required to construct
      # Settings() at all, even though nothing in this job makes a real API call
      # (fast unit tests use fakes; `eval --retrieval-only` never touches Anthropic).
      # A real key is deliberately NOT needed here -- see nightly-eval.yml for that.
      ANTHROPIC_API_KEY: ci-placeholder-unused
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run pytest -m "not slow and not live_api" -q
      - run: uv run pytest -m "slow and not live_api" -q  # exercises real local models (embedding, cross-encoder), still zero API cost
      - name: Retrieval-only eval gate
        run: uv run python -m app.main eval --index data/index --retrieval-only
        env:
          PYTHONPATH: src
```

**Verify** (Chunk 8.6): push and confirm the job runs and passes on GitHub, not just "looks right" locally.

**Commit**: `git add .github/workflows/cheap-gate.yml && git commit -m "[Infra] CI: cheap-gate runs tests + retrieval-only eval on every push"`.

---

### Chunk 8.5 — `.github/workflows/nightly-eval.yml`

**Files**: Create: `.github/workflows/nightly-eval.yml`.

```yaml
name: nightly-eval

on:
  schedule:
    - cron: "0 8 * * *"  # 08:00 UTC daily
  workflow_dispatch: {}

jobs:
  full-eval:
    runs-on: ubuntu-latest
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      LANGFUSE_PUBLIC_KEY: ${{ secrets.LANGFUSE_PUBLIC_KEY }}
      LANGFUSE_SECRET_KEY: ${{ secrets.LANGFUSE_SECRET_KEY }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - name: Full eval gate + baseline update
        run: uv run python -m app.main eval --index data/index --save-baseline
        env:
          PYTHONPATH: src
      - name: Commit updated baseline
        if: success()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add eval/baselines/
          git diff --cached --quiet || git commit -m "[Data] Eval: nightly baseline update"
          git push
```

Note: `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` secrets are optional — `get_tracer` already falls back to `NoOpTracer()` when unset (Block 7), so this workflow works with or without the user having set up Langfuse Cloud yet.

**Verify** (Chunk 8.6): trigger manually via `gh workflow run nightly-eval.yml` (or the GitHub UI) after push, confirm it actually runs and either passes or fails for a real, inspectable reason — not left as an untested cron waiting for 08:00 UTC.

**Commit**: `git add .github/workflows/nightly-eval.yml && git commit -m "[Infra] CI: nightly-eval runs full judge-based metrics on schedule/manual trigger"`.

---

### Chunk 8.6 — Push and verify both workflows actually run

Not TDD — real end-to-end infra verification, matching Block 7's Chunk 7.10 precedent (except this one isn't blocked on anything the user needs to set up first).

1. `git push` (all of Chunks 8.1-8.5's commits).
2. Confirm `cheap-gate.yml` triggered automatically on the push (`gh run list --workflow=cheap-gate.yml`) and passed.
3. Add `ANTHROPIC_API_KEY` (and optionally `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`) as GitHub Actions repository secrets (`gh secret set ANTHROPIC_API_KEY`) — real key, real (small, judge-only-on-8-questions) cost per run.
4. `gh workflow run nightly-eval.yml` (manual trigger), confirm it runs and produces a real pass/fail result.
5. If either workflow fails for an environment reason (missing system dependency for `sentence-transformers`/`pymupdf` on `ubuntu-latest`, `uv sync` cache behavior, etc.) — not a logic bug — fix the YAML directly rather than the Python code, and note the fix in `BUGS.md` if the root cause reveals something worth remembering (e.g., a CPU-only torch wheel needing an explicit index URL on Linux CI that wasn't needed on Windows dev).

## Technical Debt Strategy

Known shortcuts, to `BUGS.md` if not addressed:
- `query`'s citation display prints raw `chunk_id`s (e.g. `abc123`), not resolved to a human-readable `Ch. 4: Energy Management, p. 4-1` location — the chunk metadata needed for that already exists (`chapter_number`, `chapter_title`, `section_title`, and the not-yet-wired `printed_page_label` per `BUGS.md`'s Ingestion section) but formatting it for CLI/README display is Block 9 (Portfolio Deliverables) territory, not this block's CLI-completion scope.
- `nightly-eval.yml`'s baseline auto-commit step pushes directly to whatever branch triggered it — fine for a solo-portfolio repo with no branch protection, would need a PR-based flow (or at least a protected-branch check) if this were ever a team repo.
- `cheap-gate.yml` runs the `@pytest.mark.slow` suite (loads the real embedding + cross-encoder models) on every push, not just `--retrieval-only` — this is a real per-push time cost (rerank alone measured ~5.3s/candidate-batch on the real corpus per `BUGS.md`); acceptable for a CLAUDE.md-described CPU-only, CI-realistic gate, revisit if push frequency ever makes this annoying.
- The GitHub remote's exact provisioning (repo name, whether an existing empty repo already exists under the user's account) is deliberately left to be confirmed interactively at Chunk 8.0's build time rather than assumed in this plan.

## Persistence

Saved to `docs/plans/2026-07-16-ask-my-docs-block8-cli-ci-plan.md`.

**Ready to start building? Use `/build`.**
