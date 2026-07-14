# Block 6 Implementation Plan — Evaluation Harness

**Date**: 2026-07-14
**Parent plan**: `2026-07-11-ask-my-docs-implementation-plan.md` (Block 6 sketch)
**Design doc**: `2026-07-10-ask-my-docs-design.md`

## Header

- **Goal**: Build a repeatable evaluation harness over the 8 confirmed design-doc sample questions — retrieval metrics (Recall@k, MRR, nDCG) against labeled ground truth, an LLM-judge for answer correctness/completeness, a local response cache to avoid re-spending on unchanged inputs, and git-commit-tagged baseline storage with tolerance-band comparison — so future changes to retrieval/rerank/prompts can be checked for regressions instead of eyeballed via one-off spot-checks.
- **Architecture**: `src/eval/schema.py` (golden dataset + result schemas) → `src/eval/retrieval_metrics.py` (pure functions, no API calls) → `src/eval/relevance.py` (one-time offline judge that labels golden ground truth — not part of the repeatable eval run) → `src/eval/judge.py` (`judge_answer`, the repeatable per-question answer-quality judge) → `src/eval/cache.py` (sqlite response cache) → `src/eval/baseline.py` (save/load/compare) → `src/eval/pipeline.py` (`run_eval`, composes everything, the only function a future CI gate calls).
- **Design patterns**: Same structured-output pattern as Blocks 4-5 (`client.messages.parse(..., output_format=...)`), SDK-native retry/timeout, `thinking` disabled, fail-safe defaults on missing/malformed judge output (same shape as `citations.verify`). **New this block**: a *ground-truth labeling* judge (`relevance.py`) is architecturally distinct from the *repeatable eval* judge (`judge.py`) — the former runs once to produce checked-in data, the latter runs on every `run_eval` call.
- **Tech stack**: `anthropic` SDK (existing), `claude-haiku-4-5-20251001` for both judges (matches `eval.judge_model`'s existing default), `PyYAML` (already an indirect dependency via `pydantic-settings[yaml]`, now also used to load `eval/golden/questions.yaml`), stdlib `sqlite3` for the cache and stdlib `subprocess` for the git commit sha — no new third-party dependencies.

## Conventions Check (per `/plan` workflow, adapted per `CLAUDE.md` — no frontend/Supabase steps apply)

- **Reuse audit**: `hybrid_retrieve` (`src/retrieval/hybrid.py`) and `rerank` (`src/rerank/cross_encoder.py`) are called directly by the eval orchestrator to get the exact ranked candidate list retrieval metrics score against — mirrors `generate.pipeline.answer_question`'s own internal calls, not a new wrapper. `answer_with_verified_citations` (`src/citations/pipeline.py`, Block 5) is reused whole for the final answer + coverage/low_confidence — **not** decomposed, even though this means retrieval/rerank run twice per eval question (once for metrics, once inside `answer_with_verified_citations`). Both stages are pure CPU, zero API cost — the double-run costs milliseconds, not dollars, and avoids touching two already-shipped, audited orchestrators' return contracts for an internal efficiency gain. Same reasoning as Block 5's Decision 3 (`citations/pipeline.py`'s second `get_chunk_texts` fetch). `get_chunk_texts` (`src/ingest/vector_index.py`) is reused for the wide-candidate-set fetch in `relevance.py`. `generate.prompt.PROMPT_VERSION` and `citations.prompt.PROMPT_VERSION` are reused (imported, not duplicated) to tag baseline runs. No existing eval/metrics/judge/cache/baseline code exists anywhere in `src/` — `src/eval/__init__.py` is an empty placeholder package.
- **Test style**: pytest, `@pytest.mark.live_api` (skipped unless `RUN_LIVE_API_TESTS=1`) for real-judge-call tests, `@pytest.mark.slow` for anything touching the real corpus indexes — both markers already registered in `pyproject.toml`.
- **Config-isolation check**: new `eval.*` fields (`golden_path`, `judge_max_tokens`, `judge_max_retries`, `judge_timeout_seconds`, `cache_path`, `baseline_dir`, `tolerance`, `retrieval_k`) are infra constants — safe to construct `EvalConfig(...)` directly in tests, same category as every other block's config so far. `eval/golden/questions.yaml` and `eval/baselines/*.json` are **checked-in data, not gitignored** — the golden dataset and baseline history are part of this project's portfolio value (proof the eval harness actually catches regressions over time), same reasoning as `config.yaml` itself being checked in. `data/eval_cache.sqlite3` **is** gitignored (already covered by the existing `data/` pattern in `.gitignore`) — it's a pure performance optimization for eval-harness debugging, regenerable, and would just be repo noise.
- **Third-party API to verify with a throwaway script before RED** (build.md step 2): none new — Chunk 5.3 already probed `client.messages.parse` with a nested-list structured-output shape (`list[CitationVerdict]`) and `temperature` alongside `thinking: disabled`. `judge.py`'s and `relevance.py`'s structured outputs are the same shape class (flat model / nested list respectively), no new API surface to probe.
- **Probe-verified fixture requirement**: Chunk 6.3's real relevance-labeling run *is* the probe — it's the one-time act of establishing ground truth against the real corpus, not a synthetic fixture standing in for it. Chunk 6.4's live-judge test needs its own small probe-verified fixture (one answer that's clearly correct+complete, one that's clearly wrong or half-answered), same convention as Blocks 2-5.

### Decisions made at plan time (not deferred to build)

1. **Retrieval ground truth is LLM-labeled against a wide candidate set, then user-reviewed — not auto-derived from any single retrieval config's own ranking.** Per the user's explicit choice (2026-07-14) over fully-manual labeling or skipping ground truth entirely. Deriving "relevant" purely from "what got ranked top-N by the system under test" would make Recall@k/MRR/nDCG circular (a config change that hurts real retrieval quality could still score perfectly if the *same* config change also generated its own ground truth). `relevance.py`'s judge instead sees a deliberately wide candidate set (`top_n=25`, wider than any single rerank config's `top_k=5`) and labels each candidate independently of its rank. The user then reviews and corrects the 8 questions' labels by hand (`GoldenQuestion.reviewed`), which is what actually makes the ground truth trustworthy enough to gate on — the LLM labeling pass just makes that review fast (correcting a draft) instead of starting from a blank candidate list.
2. **The answer-quality judge scores two independent boolean dimensions per question — `correct` and `complete` — not a single combined score.** Per the user's explicit choice (2026-07-14) over correctness-only or a three-dimension correctness+completeness+groundedness split. Completeness is a **new** metric this project didn't have before: Block 4's spot-check found question 3 (short-field vs. soft-field takeoff) answered only half the comparison, and `BUGS.md` explicitly logged that this needs "a metric that would catch answered half the question" — `correct` alone wouldn't flag a half-answer as a failure if the half it did answer was accurate. Groundedness (does the answer's content match its cited chunks) is deliberately excluded as its own judge dimension — Block 5's `coverage` score already measures per-citation faithfulness on every live query, and `run_eval` reuses that value directly rather than re-deriving a redundant third judge dimension.
3. **The answer-quality judge is called once per golden question, not batched across all 8 in one call.** Rejected: batching all 8 Q&A pairs into a single prompt (the pattern Block 5's `verify_citations` uses for a single answer's citations). Unlike a single answer's citations (all grounded in the same excerpts, same context), 8 independent questions crammed into one long prompt risk the model cross-contaminating judgments between unrelated Q&A pairs — a real risk a single-answer batch doesn't have. 8 cheap Haiku calls per eval run is not a cost concern (this harness runs on-demand/nightly, not per live query).
4. **`relevance.py` (ground-truth labeling) and `judge.py` (repeatable answer-quality judge) are separate modules with separate prompts, even though both are Haiku judges.** They run at fundamentally different times for different purposes: `relevance.py` runs once (or on-demand when the golden set is edited) to produce checked-in data a human then reviews; `judge.py` runs on every `run_eval` call and its output is never manually corrected. Collapsing them into one module would blur "this judges training data" vs. "this judges the system," a distinction the design doc's own `auto_generated`/`reviewed` schema flags exist to preserve.
5. **`reference_notes` (the answer-quality judge's grading rubric per question) are authored by hand during Chunk 6.3's real-corpus touchpoint, not LLM-generated.** Because they *are* the standard `judge.py` grades against — having the same class of model that will later be judged also write its own grading rubric risks the rubric drifting toward "whatever the model tends to say" rather than "what the handbook actually says." Written once, by reading the real relevant-chunk text collected during the same session, presented for the user's review alongside the relevance labels.
6. **Only `reviewed=True` golden questions count toward `run_eval`'s aggregate metrics and baseline comparison.** `auto_generated=True, reviewed=False` questions may exist transiently after Chunk 6.3's labeling pass but before manual review; including them in a metric a future CI gate trusts would let unverified LLM-labeled ground truth silently drive pass/fail decisions. Mirrors the design doc's own stated purpose for the `auto_generated`/`reviewed` distinction.
7. **The response cache is stdlib `sqlite3`, keyed on `(question_id, config_hash)`, storing the full per-question `EvalResult` as a JSON blob.** Rejected: a new dependency like `diskcache` (this project has zero cache-library precedent and sqlite3 is already sufficient for a single-writer, single-reader local cache); a plain JSON-file-per-key cache (a single sqlite file avoids a `data/` directory filling with hundreds of small files as the golden set grows). `config_hash` is a sha256 of the sorted-JSON dump of `settings.retrieval`/`rerank`/`generation`/`citations`/`eval` — any config change that could alter a query's output invalidates that config's cache entries, without needing to enumerate which specific field changed.
8. **Baseline files are checked-in JSON under `eval/baselines/`, named `<UTC-timestamp>_<commit-sha8>.json`, loaded by filename sort (most recent last).** Rejected: a single mutable `latest.json` overwritten each run (loses history — the design doc's own "eval report showing... a caught regression example" acceptance criterion for Block 9 needs multiple historical runs to diff against, not just the newest one).

## Block 6: Evaluation Harness

**Success criteria**

- [x] `GoldenQuestion`/`EvalResult`/`EvalRunResult` schemas exist; `eval/golden/questions.yaml` seeded with the 8 confirmed design-doc sample questions (ids, question text — `relevant_chunk_ids`/`reference_notes` populated by Chunk 6.3).
- [x] Retrieval metrics (`recall_at_k`, `mrr`, `ndcg`) are pure functions, deterministic, zero API calls, with edge-case coverage (empty ground truth, no hits, ties). **Real-corpus finding, fixed same session**: the first end-to-end run exposed `mrr` was missing the empty-`relevant_ids` vacuous-truth guard `recall_at_k`/`ndcg` both have — q8 (deliberately zero relevant docs) scored `recall=1.0, ndcg=1.0` but `mrr=0.0`. Fixed via TDD (`mrr` now returns `1.0` for empty `relevant_ids`, consistent with the other two).
- [x] Real-corpus relevance labeling: all 8 golden questions have LLM-labeled `relevant_chunk_ids` (wide 25-candidate set, judged independently of rank) and hand-authored `reference_notes`, reviewed and corrected by the user, `reviewed=True`. q7/q8 landed exactly as the design doc intended (1 narrow hit, 0 hits for the deliberate out-of-scope case). Real finding: q4 (crosswind takeoff errors) has no dedicated "common errors" bulleted list anywhere in the corpus, unlike every comparable maneuver — confirmed by auditing the full 25-candidate pool, not just the labeled subset — documented in its `reference_notes` rather than assumed away.
- [x] Answer-quality judge (`judge_answer`) scores `correct`/`complete` per question via a real Haiku call, structured output, SDK-native retry/timeout, thinking disabled; malformed/truncated output raises a clear `RuntimeError` naming `eval.judge_max_tokens`.
- [x] Live-judge test: one clearly-correct-and-complete answer judged `correct=True, complete=True`; one clearly-wrong-or-half-answered answer judged `correct=False` or `complete=False` (probe-verified fixture: short-field/soft-field takeoff, full vs. short-field-only answer — probe run 2026-07-14 confirmed `correct=True/complete=True` vs. `correct=True/complete=False`).
- [x] Response cache: identical `(question_id, config_hash)` returns the cached result without a second API call; a config change invalidates the cache (different `config_hash` misses). **Real-corpus caveat found**: `config_hash` only captures `Settings` fields, not code/logic changes — the `mrr` fix above did not change the hash, so the cache would have silently kept serving the pre-fix `mrr=0.0` for q8 had the cache not been cleared manually before the corrected baseline run. Not fixed (would need a code-version component in the hash, e.g. a package version string); logged to `BUGS.md`.
- [x] Baseline save/load/compare: `save_baseline` writes a git-commit + prompt-version-tagged JSON; `compare_to_baseline` flags a metric as failing only when it drops by more than `eval.tolerance`, not on any drop at all (tolerance-band, not hard-cutoff, per the design doc's non-determinism acceptance criterion).
- [x] `run_eval` orchestrator composes retrieval metrics + `answer_with_verified_citations` + `judge_answer` + cache, aggregates only `reviewed=True` questions.
- [x] Real end-to-end run: `run_eval` executed over the real reviewed golden set against the real corpus indexes (2026-07-14); first baseline saved (`eval/baselines/20260714T151052Z_dfac1522.json`): `mean_recall_at_k=0.616, mean_mrr=0.906, mean_ndcg=0.783, mean_coverage=1.000, low_confidence_rate=0.000, correctness_rate=0.750, completeness_rate=0.500`. Question 3's completeness was checked via an independent second generation call in the same session: both runs scored `correct=True, complete=True` — stable this session (contrast with Block 4's originally-logged half-answer gap, not reproduced here; still not claimed fixed, since one stable pair of runs isn't proof against non-deterministic generation). **Two real findings surfaced, both logged to `BUGS.md`, neither fixed this session (out of Block 6's scope — the harness's job was to catch these, not fix them)**: (1) HIGH — q4 (crosswind errors): the model fabricated an 8-item "According to the handbook" errors list not present in its single cited chunk; the judge caught it directly ("fabricates the existence of a formal errors list and presents inferences as direct handbook content"). (2) q1 (VMC/VSO) scored `correct=True` on the very first run and `correct=False` on the corrected re-run of the identical question — real generation non-determinism, since `GenerationConfig` has no `temperature` field and defaults to the Anthropic SDK's default. Concrete evidence for why this harness compares against tolerance bands, not single-run pass/fail.

---

### Chunk 6.1 — golden dataset schema + seed data (no API calls)

**Files**: Create `src/eval/schema.py`; Create `eval/golden/questions.yaml`; Modify `src/config/settings.py` (`EvalConfig.golden_path`); Modify `config.yaml`, `config.example.yaml`; Create `tests/eval/test_schema.py`.

**Step 1 — failing tests**:

```python
from pathlib import Path

from eval.schema import GoldenQuestion, load_golden_questions


def test_load_golden_questions_parses_seeded_yaml(tmp_path):
    path = tmp_path / "questions.yaml"
    path.write_text(
        "- id: q1_vmc_vso\n"
        "  question: \"What's the difference between VMC and VSO?\"\n"
        "  relevant_chunk_ids: []\n"
        "  reference_notes: \"\"\n"
        "  auto_generated: false\n"
        "  reviewed: false\n"
    )

    questions = load_golden_questions(path)

    assert len(questions) == 1
    assert isinstance(questions[0], GoldenQuestion)
    assert questions[0].id == "q1_vmc_vso"


def test_real_golden_file_has_the_eight_confirmed_sample_questions():
    questions = load_golden_questions(Path("eval/golden/questions.yaml"))

    assert len(questions) == 8
    assert {q.id for q in questions} == {
        "q1_vmc_vso",
        "q2_secondary_stall",
        "q3_shortfield_softfield",
        "q4_crosswind_errors",
        "q5_energy_rules",
        "q6_upset_recovery",
        "q7_wings_program",
        "q8_autorotation_oos",
    }
    assert all(q.reviewed is False for q in questions)  # true until Chunk 6.3's manual review
```

**Step 2 — verify failure**: `uv run pytest tests/eval -q` → `ModuleNotFoundError: No module named 'eval.schema'`.

**Step 3 — minimal implementation**:

`src/eval/schema.py`:
```python
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
```

`eval/golden/questions.yaml` (seeded from the design doc's 8 confirmed questions, `relevant_chunk_ids`/`reference_notes` left empty pending Chunk 6.3):
```yaml
- id: q1_vmc_vso
  question: "What's the difference between VMC and VSO?"
  relevant_chunk_ids: []
  reference_notes: ""
  auto_generated: false
  reviewed: false
- id: q2_secondary_stall
  question: "What is a secondary stall and how does it differ from an accelerated stall?"
  relevant_chunk_ids: []
  reference_notes: ""
  auto_generated: false
  reviewed: false
- id: q3_shortfield_softfield
  question: "How does a short-field takeoff differ from a soft-field takeoff?"
  relevant_chunk_ids: []
  reference_notes: ""
  auto_generated: false
  reviewed: false
- id: q4_crosswind_errors
  question: "What are the common errors during a crosswind takeoff?"
  relevant_chunk_ids: []
  reference_notes: ""
  auto_generated: false
  reviewed: false
- id: q5_energy_rules
  question: "Explain the three basic rules of energy control."
  relevant_chunk_ids: []
  reference_notes: ""
  auto_generated: false
  reviewed: false
- id: q6_upset_recovery
  question: "What should a pilot do during upset prevention and recovery training?"
  relevant_chunk_ids: []
  reference_notes: ""
  auto_generated: false
  reviewed: false
- id: q7_wings_program
  question: "What is the FAA Wings Program?"
  relevant_chunk_ids: []
  reference_notes: ""
  auto_generated: false
  reviewed: false
- id: q8_autorotation_oos
  question: "Does this handbook cover helicopter autorotation procedures?"
  relevant_chunk_ids: []
  reference_notes: ""
  auto_generated: false
  reviewed: false
```

`EvalConfig.golden_path` addition (`src/config/settings.py`, `config.yaml`, `config.example.yaml`, kept in sync in this commit):
```python
class EvalConfig(BaseModel):
    judge_model: str = "claude-haiku-4-5-20251001"
    judge_temperature: float = 0.0
    golden_path: str = "eval/golden/questions.yaml"
```

**Step 4 — verify pass**: `uv run pytest tests/eval -q` → 2 passed. Full suite green.

**Step 5 — commit**: `git add src/eval/schema.py eval/golden/questions.yaml tests/eval/test_schema.py src/config/settings.py config.yaml config.example.yaml && git commit -m "[Feature] Eval: golden dataset schema, 8 seeded sample questions"`

---

### Chunk 6.2 — retrieval metrics (pure functions, no API calls)

**Files**: Create `src/eval/retrieval_metrics.py`; Create `tests/eval/test_retrieval_metrics.py`.

**Step 1 — failing tests**:

```python
from eval.retrieval_metrics import mrr, ndcg, recall_at_k


def test_recall_at_k_counts_hits_within_top_k():
    assert recall_at_k(["a", "b", "c", "d"], {"b", "d", "z"}, k=3) == 2 / 3


def test_recall_at_k_is_vacuously_perfect_with_no_relevant_docs():
    assert recall_at_k(["a", "b"], set(), k=5) == 1.0


def test_mrr_scores_by_first_hit_rank():
    assert mrr(["a", "b", "c"], {"c"}) == 1 / 3


def test_mrr_is_zero_with_no_hit():
    assert mrr(["a", "b"], {"z"}) == 0.0


def test_ndcg_penalizes_lower_ranked_hits():
    perfect = ndcg(["a", "b"], {"a", "b"}, k=2)
    reversed_order = ndcg(["b", "a"], {"a"}, k=2)
    assert perfect == 1.0
    assert 0.0 < reversed_order < 1.0


def test_ndcg_is_vacuously_perfect_with_no_relevant_docs():
    assert ndcg(["a", "b"], set(), k=2) == 1.0
```

**Step 2 — verify failure**: `uv run pytest tests/eval -q` → `ModuleNotFoundError: No module named 'eval.retrieval_metrics'`.

**Step 3 — minimal implementation**:

`src/eval/retrieval_metrics.py`:
```python
import math


def recall_at_k(predicted_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 1.0
    hits = len(set(predicted_ids[:k]) & relevant_ids)
    return hits / len(relevant_ids)


def mrr(predicted_ids: list[str], relevant_ids: set[str]) -> float:
    for rank, chunk_id in enumerate(predicted_ids, start=1):
        if chunk_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg(predicted_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 1.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(predicted_ids[:k], start=1)
        if chunk_id in relevant_ids
    )
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 1.0
```

**Step 4 — verify pass**: `uv run pytest tests/eval -q` → 8 passed. Full suite green.

**Step 5 — commit**: `git add src/eval/retrieval_metrics.py tests/eval/test_retrieval_metrics.py && git commit -m "[Feature] Eval: Recall@k, MRR, nDCG as pure deterministic functions"`

---

### Chunk 6.3 — relevance labeling module + real ground-truth run (manual review required)

**Pre-step (build.md step 2)**: no new API probe needed (nested-list structured output already probe-verified in Block 5's Chunk 5.3).

**Files**: Create `prompts/relevance_v1.md`; Create `src/eval/relevance.py`; Create `tests/eval/test_relevance.py`.

**Step 1 — failing tests** (fake-client pattern, same shape as `citations/verify.py`'s tests):

```python
from eval.relevance import RelevanceLabelingResult, RelevanceVerdict, label_relevance


def test_label_relevance_returns_only_relevant_chunk_ids():
    verdicts = RelevanceLabelingResult(
        verdicts=[
            RelevanceVerdict(chunk_id="stall001", relevant=True),
            RelevanceVerdict(chunk_id="wings01", relevant=False),
        ]
    )

    class FakeMessages:
        def parse(self, **kwargs):
            class FakeResponse:
                parsed_output = verdicts

            return FakeResponse()

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    candidates = [("stall001", "text a"), ("wings01", "text b")]

    result = label_relevance(FakeClient(), "What causes a stall?", candidates, EvalConfig())

    assert result == ["stall001"]


def test_label_relevance_treats_missing_verdict_as_not_relevant():
    verdicts = RelevanceLabelingResult(verdicts=[RelevanceVerdict(chunk_id="a", relevant=True)])

    class FakeMessages:
        def parse(self, **kwargs):
            class FakeResponse:
                parsed_output = verdicts

            return FakeResponse()

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    candidates = [("a", "text a"), ("missing999", "text b")]

    result = label_relevance(FakeClient(), "q", candidates, EvalConfig())

    assert result == ["a"]
```

(`EvalConfig` import and a truncated-output-raises-`RuntimeError` test follow the exact pattern of `tests/citations/test_verify.py`'s Chunk 5.3 tests — omitted here for brevity, included at build time.)

**Step 2 — verify failure**: `uv run pytest tests/eval -q` → `ModuleNotFoundError: No module named 'eval.relevance'`.

**Step 3 — minimal implementation**:

`prompts/relevance_v1.md`:
```markdown
You are building a ground-truth relevance judgment for a retrieval evaluation dataset over the FAA Airplane Flying Handbook. For each excerpt below, decide whether it is relevant to the question — mark `relevant: true` only if a reader trying to answer the question would want this excerpt. Judge each excerpt independently of any other excerpt's position or content; there is no ranking here, only a yes/no relevance call per excerpt.

Question: {question}

Excerpts:
{context}

Return exactly one verdict for every chunk id listed above.
```

`src/eval/relevance.py` (mirrors `citations/verify.py`'s structure: `with_options` → `messages.parse` → fail-safe default → `ValidationError` → `RuntimeError`):
```python
from pathlib import Path

from pydantic import BaseModel, ValidationError

from config.settings import EvalConfig

_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / "relevance_v1.md"


class RelevanceVerdict(BaseModel):
    chunk_id: str
    relevant: bool


class RelevanceLabelingResult(BaseModel):
    verdicts: list[RelevanceVerdict]


def label_relevance(
    client, question: str, candidates: list[tuple[str, str]], config: EvalConfig
) -> list[str]:
    context = "\n\n".join(f"[{chunk_id}] {text}" for chunk_id, text in candidates)
    prompt = _TEMPLATE_PATH.read_text().format(question=question, context=context)

    scoped_client = client.with_options(max_retries=config.judge_max_retries, timeout=config.judge_timeout_seconds)
    try:
        response = scoped_client.messages.parse(
            model=config.judge_model,
            max_tokens=config.judge_max_tokens,
            temperature=config.judge_temperature,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
            output_format=RelevanceLabelingResult,
        )
    except ValidationError as e:
        raise RuntimeError(
            f"Relevance judge response could not be parsed, likely truncated by "
            f"eval.judge_max_tokens (currently {config.judge_max_tokens})."
        ) from e

    verdicts = {v.chunk_id: v.relevant for v in response.parsed_output.verdicts}
    return [chunk_id for chunk_id, _ in candidates if verdicts.get(chunk_id, False)]
```

Also add `EvalConfig.judge_max_tokens`/`judge_max_retries`/`judge_timeout_seconds` (`src/config/settings.py`, `config.yaml`, `config.example.yaml`):
```python
class EvalConfig(BaseModel):
    judge_model: str = "claude-haiku-4-5-20251001"
    judge_temperature: float = 0.0
    golden_path: str = "eval/golden/questions.yaml"
    judge_max_tokens: int = 1024
    judge_max_retries: int = 3
    judge_timeout_seconds: float = 30.0
```

**Step 4 — verify pass**: `uv run pytest tests/eval -q` → passes. Full suite green.

**Step 5 — commit**: `git add prompts/relevance_v1.md src/eval/relevance.py tests/eval/test_relevance.py src/config/settings.py config.yaml config.example.yaml && git commit -m "[Feature] Eval: relevance-labeling judge for ground-truth chunk_ids"`

**Step 6 — real ground-truth run (manual, not a commit-blocking test)**: throwaway script (scratchpad) — for each of the 8 golden questions, call `hybrid_retrieve` with a temporarily widened `top_n=25` (config override, not a `config.yaml` change), fetch candidate text via `get_chunk_texts`, call `label_relevance`. Write the returned `relevant_chunk_ids` into `eval/golden/questions.yaml`, set `auto_generated: true`. While the real chunk text is on screen, hand-author each question's `reference_notes` (2-4 bullet points of what a correct, complete answer must state — per Decision 5, not LLM-generated). **Present both to the user for review**: correct/add/remove `relevant_chunk_ids`, edit `reference_notes` as needed, then flip `reviewed: true` once satisfied. Commit the reviewed `eval/golden/questions.yaml` separately: `git add eval/golden/questions.yaml && git commit -m "[Data] Eval: ground-truth labels + reference notes reviewed for all 8 golden questions"`.

---

### Chunk 6.4 — answer-quality judge: correctness + completeness (real judge call)

**Files**: Create `prompts/judge_v1.md`; Create `src/eval/judge.py`; Create `tests/eval/test_judge.py`.

**Step 1 — failing tests** (fake-client unit tests mirroring Chunk 6.3's pattern; asserts `with_options`/`parse` kwargs, truncation → `RuntimeError`):

```python
from eval.judge import AnswerJudgment, judge_answer


def test_judge_answer_configures_client_and_returns_judgment():
    judgment = AnswerJudgment(correct=True, complete=False, reasoning="Covers short-field only.")

    class FakeMessages:
        def __init__(self):
            self.parse_kwargs = None

        def parse(self, **kwargs):
            self.parse_kwargs = kwargs

            class FakeResponse:
                parsed_output = judgment

            return FakeResponse()

    class FakeScopedClient:
        def __init__(self):
            self.messages = FakeMessages()

    class FakeClient:
        def __init__(self):
            self.with_options_kwargs = None
            self.scoped = FakeScopedClient()

        def with_options(self, **kwargs):
            self.with_options_kwargs = kwargs
            return self.scoped

    client = FakeClient()
    config = EvalConfig(judge_max_tokens=777, judge_max_retries=5, judge_timeout_seconds=9.0)

    result = judge_answer(client, "q", "answer text", "must cover X and Y", config)

    assert client.with_options_kwargs == {"max_retries": 5, "timeout": 9.0}
    assert client.scoped.messages.parse_kwargs["thinking"] == {"type": "disabled"}
    assert client.scoped.messages.parse_kwargs["output_format"] is AnswerJudgment
    assert result.correct is True
    assert result.complete is False


def test_judge_answer_raises_clear_error_on_truncated_output():
    class FakeMessages:
        def parse(self, **kwargs):
            AnswerJudgment.model_validate_json('{"correct": tr')  # raises

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    with pytest.raises(RuntimeError, match="judge_max_tokens"):
        judge_answer(FakeClient(), "q", "a", "notes", EvalConfig(judge_max_tokens=10))
```

**Step 2 — verify failure**: `uv run pytest tests/eval -q` → `ModuleNotFoundError: No module named 'eval.judge'`.

**Step 3 — minimal implementation**:

`prompts/judge_v1.md`:
```markdown
You are grading an answer generated from the FAA Airplane Flying Handbook against a reference rubric. Score two independent dimensions:

- `correct`: true only if every claim the answer makes is factually consistent with the reference notes (no fabricated or contradicted facts).
- `complete`: true only if the answer addresses everything the reference notes say it should — a partial answer (e.g. answering only one half of a comparison question) is not complete, even if the part it does answer is accurate.

Question: {question}

Answer: {answer_text}

Reference notes (what a correct, complete answer must cover): {reference_notes}

Briefly explain your reasoning, then give your `correct`/`complete` verdicts.
```

`src/eval/judge.py`:
```python
from pathlib import Path

from pydantic import BaseModel, ValidationError

from config.settings import EvalConfig

_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / "judge_v1.md"


class AnswerJudgment(BaseModel):
    correct: bool
    complete: bool
    reasoning: str


def judge_answer(
    client, question: str, answer_text: str, reference_notes: str, config: EvalConfig
) -> AnswerJudgment:
    prompt = _TEMPLATE_PATH.read_text().format(
        question=question, answer_text=answer_text, reference_notes=reference_notes
    )

    scoped_client = client.with_options(max_retries=config.judge_max_retries, timeout=config.judge_timeout_seconds)
    try:
        response = scoped_client.messages.parse(
            model=config.judge_model,
            max_tokens=config.judge_max_tokens,
            temperature=config.judge_temperature,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
            output_format=AnswerJudgment,
        )
    except ValidationError as e:
        raise RuntimeError(
            f"Answer-quality judge response could not be parsed, likely truncated by "
            f"eval.judge_max_tokens (currently {config.judge_max_tokens})."
        ) from e

    return response.parsed_output
```

**Step 4 — verify pass**: `uv run pytest tests/eval -q` → passes. Full suite green.

**Step 5 — commit**: `git add prompts/judge_v1.md src/eval/judge.py tests/eval/test_judge.py && git commit -m "[Feature] Eval: correctness+completeness answer-quality judge"`

---

### Chunk 6.5 — real judge test (slow, gated, probe-verified)

**Files**: Modify `tests/eval/test_judge.py`.

**Step 1 — failing/new test**:

```python
import anthropic

from config.settings import Settings


@pytest.mark.slow
@pytest.mark.live_api
def test_judge_answer_distinguishes_correct_complete_from_incomplete_on_real_judge():
    client = anthropic.Anthropic(api_key=Settings().anthropic_api_key)
    config = EvalConfig()

    complete = judge_answer(
        client,
        "How does a short-field takeoff differ from a soft-field takeoff?",
        "Short-field takeoffs use maximum power before brake release and climb at best "
        "angle-of-climb speed to clear an obstacle. Soft-field takeoffs use minimum weight "
        "on the wheels via back pressure and accelerate in ground effect before climbing.",
        "Must cover both short-field (max power, obstacle clearance, Vx) and soft-field "
        "(minimum wheel weight, ground effect acceleration) procedures.",
        config,
    )
    half_answer = judge_answer(
        client,
        "How does a short-field takeoff differ from a soft-field takeoff?",
        "Short-field takeoffs use maximum power before brake release and climb at best "
        "angle-of-climb speed to clear an obstacle.",
        "Must cover both short-field (max power, obstacle clearance, Vx) and soft-field "
        "(minimum wheel weight, ground effect acceleration) procedures.",
        config,
    )

    assert complete.correct is True and complete.complete is True
    assert half_answer.complete is False
```

**Step 2 — verify**: run once with `RUN_LIVE_API_TESTS=1 uv run pytest tests/eval -q -m live_api`. Record actual verdicts in a comment above the test (probe-verification convention) — strengthen the half-answer fixture if the judge doesn't discriminate.

**Step 3/4 — verify**: full suite `uv run pytest -q` (live_api skipped by default); `RUN_LIVE_API_TESTS=1 uv run pytest -q -m live_api` → all live tests (Blocks 4/5/6) pass.

**Step 5 — commit**: `git add tests/eval/test_judge.py && git commit -m "[Test] Eval: real-judge correctness/completeness discrimination"`

---

### Chunk 6.6 — response cache (sqlite, no API calls)

**Files**: Create `src/eval/cache.py`; Modify `src/config/settings.py` (`EvalConfig.cache_path`); Modify `config.yaml`, `config.example.yaml`; Create `tests/eval/test_cache.py`.

**Step 1 — failing tests**:

```python
from eval.cache import config_hash, get_cached_result, save_cached_result
from eval.schema import EvalResult


def test_config_hash_changes_when_config_changes():
    settings_a = Settings(anthropic_api_key="x")
    settings_b = Settings(anthropic_api_key="x")
    settings_b.retrieval.top_n = 99

    assert config_hash(settings_a) != config_hash(settings_b)


def test_cache_round_trips_a_result(tmp_path):
    cache_path = tmp_path / "cache.sqlite3"
    result = EvalResult(
        question_id="q1", recall_at_k=1.0, mrr=1.0, ndcg=1.0,
        coverage=1.0, low_confidence=False, correct=True, complete=True,
    )

    assert get_cached_result(cache_path, "q1", "hash-a") is None

    save_cached_result(cache_path, "q1", "hash-a", result)

    cached = get_cached_result(cache_path, "q1", "hash-a")
    assert cached == result


def test_cache_miss_on_different_config_hash(tmp_path):
    cache_path = tmp_path / "cache.sqlite3"
    result = EvalResult(
        question_id="q1", recall_at_k=1.0, mrr=1.0, ndcg=1.0,
        coverage=1.0, low_confidence=False, correct=True, complete=True,
    )
    save_cached_result(cache_path, "q1", "hash-a", result)

    assert get_cached_result(cache_path, "q1", "hash-b") is None
```

**Step 2 — verify failure**: `uv run pytest tests/eval -q` → `ModuleNotFoundError: No module named 'eval.cache'`.

**Step 3 — minimal implementation**:

`src/eval/cache.py`:
```python
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
```

Add `EvalConfig.cache_path` (`src/config/settings.py`, `config.yaml`, `config.example.yaml`): `cache_path: str = "data/eval_cache.sqlite3"` (already covered by the existing `data/` gitignore pattern).

**Step 4 — verify pass**: `uv run pytest tests/eval -q` → passes. Full suite green.

**Step 5 — commit**: `git add src/eval/cache.py tests/eval/test_cache.py src/config/settings.py config.yaml config.example.yaml && git commit -m "[Feature] Eval: sqlite response cache keyed on question + config hash"`

---

### Chunk 6.7 — baseline storage + tolerance-band comparison (no API calls)

**Files**: Create `src/eval/baseline.py`; Modify `src/config/settings.py` (`EvalConfig.baseline_dir`, `EvalConfig.tolerance`); Modify `config.yaml`, `config.example.yaml`; Create `tests/eval/test_baseline.py`.

**Step 1 — failing tests**:

```python
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
```

**Step 2 — verify failure**: `uv run pytest tests/eval -q` → `ModuleNotFoundError: No module named 'eval.baseline'`.

**Step 3 — minimal implementation**:

`src/eval/baseline.py`:
```python
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
```

Add `EvalConfig.baseline_dir`/`tolerance` (`src/config/settings.py`, `config.yaml`, `config.example.yaml`): `baseline_dir: str = "eval/baselines"`, `tolerance: float = 0.1`.

**Step 4 — verify pass**: `uv run pytest tests/eval -q` → passes. Full suite green.

**Step 5 — commit**: `git add src/eval/baseline.py tests/eval/test_baseline.py src/config/settings.py config.yaml config.example.yaml && git commit -m "[Feature] Eval: git-commit-tagged baseline storage, tolerance-band comparison"`

---

### Chunk 6.8 — `run_eval` orchestrator + real end-to-end run, first baseline

**Files**: Create `src/eval/pipeline.py`; Modify `src/config/settings.py` (`EvalConfig.retrieval_k`); Modify `config.yaml`, `config.example.yaml`; Create `tests/eval/test_pipeline.py`.

**Step 1 — failing tests** (fast — monkeypatch every sub-stage, same convention as `citations/pipeline.py`'s Chunk 5.5 tests):

```python
from pathlib import Path

from eval import pipeline
from eval.pipeline import run_eval
from eval.schema import GoldenQuestion


def test_run_eval_skips_unreviewed_questions(monkeypatch):
    reviewed = GoldenQuestion(
        id="q1", question="q", relevant_chunk_ids=["a"], reference_notes="notes", reviewed=True
    )
    unreviewed = GoldenQuestion(
        id="q2", question="q", relevant_chunk_ids=["b"], reference_notes="notes", reviewed=False
    )

    calls = {"answered": []}

    def fake_hybrid_retrieve(bm25_dir, vector_db_path, question, config):
        return ["a"]

    def fake_rerank(question, candidates, config):
        return [cid for cid, _ in candidates]

    def fake_get_chunk_texts(vector_db_path, ids):
        return {cid: "text" for cid in ids}

    def fake_answer_with_verified_citations(question, client, bm25_dir, vector_db_path, settings):
        calls["answered"].append(question)

        class FakeVerified:
            answer_text = "answer"
            citations = ["a"]
            coverage = 1.0
            low_confidence = False

        return FakeVerified()

    def fake_judge_answer(client, question, answer_text, reference_notes, config):
        class FakeJudgment:
            correct = True
            complete = True

        return FakeJudgment()

    def fake_get_cached_result(cache_path, question_id, cfg_hash):
        return None

    def fake_save_cached_result(cache_path, question_id, cfg_hash, result):
        pass

    monkeypatch.setattr(pipeline, "hybrid_retrieve", fake_hybrid_retrieve)
    monkeypatch.setattr(pipeline, "rerank", fake_rerank)
    monkeypatch.setattr(pipeline, "get_chunk_texts", fake_get_chunk_texts)
    monkeypatch.setattr(pipeline, "answer_with_verified_citations", fake_answer_with_verified_citations)
    monkeypatch.setattr(pipeline, "judge_answer", fake_judge_answer)
    monkeypatch.setattr(pipeline, "get_cached_result", fake_get_cached_result)
    monkeypatch.setattr(pipeline, "save_cached_result", fake_save_cached_result)

    settings = Settings(anthropic_api_key="placeholder")

    result = run_eval(
        [reviewed, unreviewed], client=object(), bm25_dir=Path("unused"),
        vector_db_path=Path("unused"), settings=settings,
    )

    assert calls["answered"] == ["q"]  # only the reviewed question was answered
    assert len(result.results) == 1
    assert result.correctness_rate == 1.0
```

**Step 2 — verify failure**: `ModuleNotFoundError: No module named 'eval.pipeline'`.

**Step 3 — minimal implementation**:

`src/eval/pipeline.py`:
```python
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from citations.pipeline import answer_with_verified_citations
from config.settings import Settings
from eval.cache import config_hash, get_cached_result, save_cached_result
from eval.judge import judge_answer
from eval.retrieval_metrics import mrr, ndcg, recall_at_k
from eval.schema import EvalResult, EvalRunResult, GoldenQuestion
from generate.prompt import PROMPT_VERSION as GENERATION_PROMPT_VERSION
from citations.prompt import PROMPT_VERSION as CITATIONS_PROMPT_VERSION
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
```

Add `EvalConfig.retrieval_k` (`src/config/settings.py`, `config.yaml`, `config.example.yaml`): `retrieval_k: int = 5` (matches `rerank.top_k`'s default — metrics score against what generation actually sees).

**Step 4 — verify pass**: `uv run pytest tests/eval -q` → passes. Full suite green.

**Step 5 — commit**: `git add src/eval/pipeline.py tests/eval/test_pipeline.py src/config/settings.py config.yaml config.example.yaml && git commit -m "[Feature] Eval: run_eval orchestrator composes metrics, judge, and cache"`

**Step 6 — real end-to-end run (manual, no new tests)**: run `run_eval` against the real handbook indexes over the full reviewed golden set. Record per-question metrics, save the first baseline (`save_baseline`), and specifically check whether question 3's `complete` score is stable across a couple of runs given the retrieval-variance finding already logged in `BUGS.md` — this is the first real signal on whether that gap is a genuine, catchable regression or session-to-session noise. Log findings to `PROJECT_HISTORY.md`/`LEARNING_NOTES.md`; check off Block 6's success criteria in this file.

---

## Technical Debt Strategy (log to `BUGS.md` at build time if accepted)

- `run_eval` calls `hybrid_retrieve`/`rerank` a second time on top of `answer_with_verified_citations`'s internal call to the same stages (Conventions Check reuse audit) — cheap (CPU-only, no API cost) at 8 golden questions; revisit if the golden set grows large enough for the duplicate CPU work to matter, or if Block 7's serving layer wants a single call path shared between live queries and eval runs.
- `judge_answer` is called once per golden question (Decision 3) rather than batched — 8x the API calls of a batched design, though still cheap on Haiku; revisit if the golden dataset grows to a size where per-question calls meaningfully affect eval-run latency or cost.
- The relevance-labeling judge (`relevance.py`) and the answer-quality judge (`judge.py`) both default to `eval.judge_model`/`judge_temperature`/`judge_max_tokens`/`judge_max_retries`/`judge_timeout_seconds` — unlike Block 5's `citations.judge_model` vs `eval.judge_model` split, these two *do* share one config namespace despite serving different purposes (one-time labeling vs. repeatable grading), since both are Haiku judges at the same block and splitting them now would be speculative. Revisit if either ever needs independently tuned retry/timeout behavior.
- `compare_to_baseline`'s tolerance is a single global `eval.tolerance` applied uniformly across all six metrics, even though retrieval metrics (deterministic, pure CPU) and judge-based metrics (non-deterministic even at temp 0) plausibly warrant different tolerance widths. Single tolerance is the simplest correct-enough start; split if a future baseline run shows a metric noisier or stricter than the shared value suits.
- No CI workflow wiring yet — `run_eval`/`compare_to_baseline` are the functions Block 8's `cheap-gate.yml`/`nightly-eval.yml` will call, but the workflow files themselves are explicitly out of scope for this block per the master plan's block split.

## Production Standards (P0)

- **Timeout Mapping**: `eval.judge_timeout_seconds` (default 30.0) passed via `client.with_options(timeout=...)` for both judges — same pattern as Blocks 4-5.
- **Error Handling**: judge API errors propagate uncaught (SDK-native bounded retry is the mitigation), same as Blocks 4-5 — final-failure structured-error/metric wiring remains Block 7's job.
- **Loading States**: N/A (no UI).
- **Live-Service Test Gate**: `@pytest.mark.live_api`, skipped unless `RUN_LIVE_API_TESTS=1` — reuses the existing gate.
