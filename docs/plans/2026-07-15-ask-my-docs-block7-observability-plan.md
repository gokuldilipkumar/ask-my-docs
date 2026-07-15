# Block 7 Implementation Plan — Observability

**Date**: 2026-07-15
**Parent plan**: `2026-07-11-ask-my-docs-implementation-plan.md` (Block 7 sketch)
**Design doc**: `2026-07-10-ask-my-docs-design.md`

## Header

- **Goal**: Every pipeline stage (bm25, vector, fusion, rerank, generate, verify) produces a traced Langfuse span; every real Anthropic API call (generation, citation verification, both eval judges) is priced against a config-driven price table and rolled into a daily running cost total; exceeding `observability.daily_cost_cap_usd` logs a warning without blocking any call.
- **Architecture**: `src/observability/tracer.py` (`Tracer`/`SpanHandle` protocols + `NoOpTracer`) → `src/observability/langfuse_tracer.py` (`LangfuseTracer` + `get_tracer(settings)` factory) → `src/observability/cost.py` (pure `calculate_cost`) → `src/observability/daily_cost.py` (sqlite running total + budget check, mirrors `eval/cache.py`'s pattern) → `src/observability/context.py` (`ObservabilityContext` bundling one tracer + one `ObservabilityConfig`, `noop_observability()` for untraced callers) → `src/observability/usage.py` (`report_usage`, the one function every real API call site calls after it gets a response). Then wiring: `hybrid_retrieve`/`rerank`/`generate_answer`/`verify_citations` each gain an optional `observability: ObservabilityContext | None` parameter and open one span around their existing body; `eval/llm_call.py`'s `call_structured_judge` gains an optional `observability_config: ObservabilityConfig | None` parameter and calls `report_usage` directly (no span — see Decision 2).
- **Design patterns**: Protocol-based `Tracer` interface (design doc's explicit requirement: "self-host later via the same tracer interface") wrapping Langfuse's real v4 SDK, which is OTel-context-based — nested `with tracer.span(...)` blocks on the *same* underlying `Langfuse` client instance automatically become parent/child spans with no manual parent-id threading, confirmed by direct probe (see Conventions Check). All new function parameters are optional with safe defaults (`NoOpTracer()` / `noop_observability()` / freshly-constructed `ObservabilityConfig()`) — every existing call site and test keeps working unmodified, same additive-parameter pattern as Block 3's `rerank.enabled=False`.
- **Tech stack**: `langfuse>=4.14.0` (already a declared dependency, never yet imported anywhere in `src/`), stdlib `sqlite3` for the daily-cost store (same pattern as `eval/cache.py`), stdlib `logging` for the non-fatal budget/pricing warnings. No new third-party dependencies.

## Conventions Check (per `/plan` workflow, adapted per `CLAUDE.md` — no frontend/Supabase steps apply)

- **Reuse audit**: `src/observability/__init__.py` exists as an empty placeholder package (created at repo scaffolding, Block 0) — no tracer/cost code exists anywhere yet. `ObservabilityConfig` already exists in `src/config/settings.py` (`langfuse_enabled: bool = True`, `daily_cost_cap_usd: float = 5.0`) and is already wired into `Settings.observability` — this block extends it, not creates it from scratch. `eval/llm_call.py`'s `call_structured_judge` (extracted this session, 2026-07-15 audit) is the existing single choke point for both eval judges (`judge_answer`, `label_relevance`) — cost-reporting for both lands there once, not duplicated per judge.
- **Composition Cost Audit** (new `/plan` checklist item, added this session's kaizen): does wiring tracing/cost through `answer_with_verified_citations` → `answer_question` duplicate any expensive step? No new retrieval/rerank/generation calls are added — this block only wraps *existing* calls in spans and adds a cost-calculation step (pure arithmetic + one sqlite write) after a response that was going to be fetched regardless. Zero added API calls.
- **Test style**: pytest. New tests are pure-function/fake-tracer unit tests (no `live_api` needed for `Tracer`/`NoOpTracer`/cost/daily-total chunks — none of those touch a real API). One new marker, `live_langfuse` (skipped unless `RUN_LIVE_LANGFUSE_TESTS=1`, mirrors the existing `live_api` gate in `tests/conftest.py`), reserved for Chunk 7.10 — the only chunk that needs a real Langfuse Cloud project.
- **Config-isolation check**: new `observability.*` fields (`cost_db_path`, `price_table`) are infra constants — safe to construct `ObservabilityConfig(...)` directly in tests. `data/daily_cost.sqlite3` is covered by the existing `data/` `.gitignore` pattern (same as `eval.cache_path`) — no new gitignore entry needed.
- **Third-party API verified with a throwaway script before RED** (build.md step 2 — this block's API surface is entirely new to the codebase, so every claim below was probed against the real installed `langfuse==4.14.0`, not assumed from docs):
  - `Langfuse(public_key=..., secret_key=..., host=...)` construction **never raises**, even with fake credentials and an unreachable host — confirms observability setup can never crash pipeline startup.
  - `client.start_as_current_observation(name=..., as_type=...)` is a context manager; nesting a second call *inside* the first's `with` block (same client instance) produces a real parent/child relationship (`LangfuseSpan` → `LangfuseGeneration`) automatically via OTel context — no manual span-id passing needed.
  - The object yielded by the `with` block (`LangfuseGeneration`/`LangfuseSpan`) has its own `.update(*, model=, usage_details=, cost_details=, output=, ...)` method — usage/cost can be attached *after* the API response is known, inside the same `with` block, without re-opening the span.
  - `client.shutdown()` after a failed export (fake host) logs a warning ("Failed to export span batch...") but **does not raise** — confirms tracer failures are non-fatal by the SDK's own design, which this block's `Tracer` wrapper should not fight against (no `try/except` needed around `tracer.span()` itself; only around our own `calculate_cost`/`record_cost` code, which *can* raise on a genuine bug).
  - `Message`/`ParsedMessage` (returned by `client.messages.parse(...)`, already used by `generate_answer`/`verify_citations`/`call_structured_judge`) has a `.usage` field (`Usage.input_tokens`, `Usage.output_tokens`) sitting right alongside the already-accessed `.parsed_output` — no restructuring needed to reach it.
- **Probe-verified fixture requirement**: n/a — no heuristic/extraction logic in this block; `calculate_cost` is pure arithmetic tested with hand-picked numbers, not corpus-derived data.

### Decisions made at plan time (not deferred to build)

1. **New observability params are additive-optional on existing functions, not new required arguments or widened return types.** `generate_answer`/`verify_citations`/`hybrid_retrieve`/`rerank` gain `observability: ObservabilityContext | None = None`; `call_structured_judge` gains `observability_config: ObservabilityConfig | None = None`. Rejected: widening return types (e.g. `generate_answer` returning `(GeneratedAnswer, Usage)`) — `BUGS.md` named this as the alternative to resolve the token-usage-discard debt item, but it would ripple into every existing caller and test that treats these functions' return values as a single object (`generate/pipeline.py`, `citations/pipeline.py`, every test asserting `.answer_text`/`.citations`/`.correct`). An additive input parameter with a safe default touches zero existing call sites.
2. **Eval judges (`judge_answer`, `label_relevance`) get cost tracking only, no dedicated Langfuse spans.** User's explicit choice (2026-07-15) over full tracing for both. Matches the design doc's traced-flow diagram exactly — it draws bm25/vector/fusion/rerank/generate/verify as the traced query-time path; eval judges run in the separate offline `eval` flow, not diagrammed as spans. They still spend real money, so `call_structured_judge` still calls `report_usage` for the daily total, just without opening a `tracer.span(...)`.
3. **Daily cost cap is a warn-only signal, never a blocking gate.** User's explicit choice (2026-07-15) over raising an exception once `daily_cost_cap_usd` is exceeded. Matches the design doc's own framing ("surfaced as a budget-runaway signal," not "enforced as a hard limit") — a hard block could interrupt an in-progress eval run or debugging session with no override. `report_usage` logs a `logging.warning(...)` and returns normally; nothing upstream needs new exception-handling.
4. **A missing price-table entry for a model fails the cost calculation loudly (`calculate_cost` raises `KeyError`) but never breaks the caller's real work** — `report_usage` catches that `KeyError`, logs a warning, records `$0.00` for that call, and returns. This mirrors this project's established fail-loud-internally / fail-safe-at-the-boundary pattern (e.g. `citations.verify`'s missing-verdict handling): the *bug* (an unpriced model slipped into config) is loud and testable in isolation, but a cost-tracking gap must never take down generation, citation verification, or an eval run.
5. **The price table ships with placeholder numbers that must be verified against Anthropic's current published pricing before Chunk 7.6 is trusted.** Same convention as `EvalConfig.judge_model`'s existing `# verify against current Anthropic model list at build time` comment — pricing pages change and this plan is not the source of truth for them. `calculate_cost`'s tests use hand-picked round numbers, not the real prices, so they're correct regardless of what the real table ends up holding.
6. **One `ObservabilityContext` (tracer + config bundled) is constructed once per live query, at the highest orchestrator that already has full `Settings`, and threaded down explicitly** — not reconstructed independently inside each leaf function. `answer_with_verified_citations` (Block 5, takes full `Settings` already) constructs it via `get_tracer(settings)` and passes the *same* instance into `answer_question` (which also gains the optional param) and `verify_citations`, so every span from one live query nests under one trace (same underlying `Langfuse` client instance — required for the automatic OTel nesting confirmed by probe). Leaf functions called standalone (e.g. directly by a future test or script) default to `None` → construct their own no-op/fresh context, so nothing *requires* a caller to know about tracing.
7. **`hybrid_retrieve` is instrumented internally with three spans (bm25, vector, fusion), matching the design doc's diagram**, rather than one span for the whole function — its existing body already calls `search_bm25`/`search_vector`/`reciprocal_rank_fusion` as three sequential steps (`src/retrieval/hybrid.py:12-20`); wrapping each in its own `tracer.span(...)` needs no change to `search_bm25`/`search_vector`/`reciprocal_rank_fusion`'s own signatures, only to `hybrid_retrieve`'s body.

## Block 7: Observability

**Success criteria**

- [x] `Tracer`/`SpanHandle` protocols exist; `NoOpTracer` satisfies them and is the safe default everywhere — no pipeline code requires Langfuse credentials to run.
- [x] `LangfuseTracer` wraps the real SDK's `start_as_current_observation`; `get_tracer(settings)` returns `NoOpTracer()` whenever `observability.langfuse_enabled=False` or either Langfuse key is unset (config-driven passthrough, same shape as `rerank.enabled=False`).
- [x] `calculate_cost` is a pure function over `(model, input_tokens, output_tokens, price_table)`; raises `KeyError` on an unpriced model.
- [x] Daily running cost total persists across process restarts (sqlite, mirrors `eval/cache.py`); `record_cost` accumulates same-day calls; a new UTC day starts a fresh total.
- [x] `report_usage` computes cost, records it to the daily total, warns (never raises) if the day's cap is exceeded or the model is unpriced. **Refined during build**: cost tracking is opt-in, gated on whether the caller was explicitly given an `ObservabilityContext`/`ObservabilityConfig` (not on `noop_observability()`'s defaulted one) — the original "every real API call site calls it after receiving a response" phrasing was found to be wrong during Chunk 7.6: calling `report_usage` unconditionally, even under the no-observability default, wrote real cost data to the real `data/daily_cost.sqlite3` on every test run, since `noop_observability()`'s default `ObservabilityConfig` still points at a real path with real price entries.
- [x] `hybrid_retrieve` produces 3 nested spans (bm25, vector, fusion); `rerank` produces 1 span — all via the optional `observability` parameter, zero behavior change when omitted.
- [x] `generate_answer` and `verify_citations` each produce 1 `as_type="generation"` span carrying `model`/`usage_details`/`cost_details`, and both call `report_usage` (only when `observability` was explicitly given).
- [x] `call_structured_judge` calls `report_usage` for both `judge_answer` and `label_relevance` (cost tracking only, per Decision 2) — zero new spans.
- [x] `answer_with_verified_citations` threads one shared `ObservabilityContext` through the whole call chain so one live query produces one nested trace, not several disconnected ones.
- [ ] Real end-to-end trace verification against a live Langfuse Cloud project (Chunk 7.10) — **still blocked**: `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` in `.env` remain empty. Every other chunk (7.0-7.9) built and tested fully without them — 122 tests green (up from 95), 4 gated.

---

### Chunk 7.0 — prerequisite check (no code)

Confirm before starting: `langfuse>=4.14.0` is already a declared dependency (`pyproject.toml:10`) and importable (`uv run python -c "import langfuse"` — verified this session). `ObservabilityConfig` already exists (`src/config/settings.py:64-66`) with `langfuse_enabled`/`daily_cost_cap_usd`; `Settings.langfuse_public_key`/`langfuse_secret_key` already exist (`src/config/settings.py:78-79`). `src/observability/__init__.py` and `tests/observability/` already exist as empty packages. `.env` has `LANGFUSE_PUBLIC_KEY=`/`LANGFUSE_SECRET_KEY=` present but **empty** (confirmed this session, `ANTHROPIC_API_KEY` is set) — every chunk through 7.8 builds and tests without them; only Chunk 7.9 is blocked until the user creates a free Langfuse Cloud project and populates both.

---

### Chunk 7.1 — `Tracer`/`SpanHandle` protocols + `NoOpTracer`

**Files**: Create `src/observability/tracer.py`; Create `tests/observability/test_tracer.py`.

**Step 1 — failing test**:
```python
from observability.tracer import NoOpTracer


def test_noop_tracer_span_is_a_context_manager_yielding_a_handle():
    tracer = NoOpTracer()

    with tracer.span("retrieval.bm25.search") as handle:
        handle.update(usage_details={"input": 10, "output": 5}, cost_details={"total": 0.01})

    # no exception anywhere above is the assertion -- NoOpTracer must accept any span name,
    # any as_type, and any update() kwargs without requiring Langfuse or raising


def test_noop_tracer_span_accepts_as_type_and_model_kwargs():
    tracer = NoOpTracer()

    with tracer.span("generate.answer", as_type="generation", model="claude-sonnet-5") as handle:
        handle.update(output="ok")
```

**Step 2 — verify failure**: `uv run pytest tests/observability -q` → `ModuleNotFoundError: No module named 'observability.tracer'`.

**Step 3 — minimal implementation**:

`src/observability/tracer.py`:
```python
from contextlib import contextmanager
from typing import Any, ContextManager, Protocol


class SpanHandle(Protocol):
    def update(self, **kwargs: Any) -> None: ...


class Tracer(Protocol):
    def span(
        self, name: str, *, as_type: str = "span", model: str | None = None
    ) -> ContextManager[SpanHandle]: ...


class _NoOpSpanHandle:
    def update(self, **kwargs: Any) -> None:
        pass


class NoOpTracer:
    @contextmanager
    def span(self, name: str, *, as_type: str = "span", model: str | None = None):
        yield _NoOpSpanHandle()
```

**Step 4 — verify pass**: `uv run pytest tests/observability -q` → 2 passed.

**Step 5 — commit**: `git add src/observability/tracer.py tests/observability/test_tracer.py && git commit -m "[Feature] Observability: Tracer/SpanHandle protocols + NoOpTracer"`

---

### Chunk 7.2 — `LangfuseTracer` + `get_tracer` factory

**Files**: Create `src/observability/langfuse_tracer.py`; Create `tests/observability/test_langfuse_tracer.py`; Modify `src/config/settings.py` (no field changes — `get_tracer` only reads existing fields).

**Step 1 — failing tests** (uses a fake Langfuse-shaped client, not the real SDK — matches this project's `FakeStructuredClient` convention, avoids any network/timeout risk in the unit suite):
```python
from config.settings import ObservabilityConfig, Settings
from observability.langfuse_tracer import LangfuseTracer, get_tracer
from observability.tracer import NoOpTracer


class FakeLangfuseClient:
    def __init__(self):
        self.observation_calls = []

    def start_as_current_observation(self, *, name, as_type="span", model=None):
        self.observation_calls.append({"name": name, "as_type": as_type, "model": model})

        class FakeSpan:
            def __init__(self):
                self.update_calls = []

            def update(self, **kwargs):
                self.update_calls.append(kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return FakeSpan()


def test_langfuse_tracer_opens_a_named_observation_and_yields_an_updatable_handle():
    client = FakeLangfuseClient()
    tracer = LangfuseTracer(client)

    with tracer.span("generate.answer", as_type="generation", model="claude-sonnet-5") as handle:
        handle.update(usage_details={"input": 10, "output": 5})

    assert client.observation_calls == [
        {"name": "generate.answer", "as_type": "generation", "model": "claude-sonnet-5"}
    ]


def test_get_tracer_returns_noop_when_langfuse_disabled():
    settings = Settings(anthropic_api_key="x")
    settings.observability.langfuse_enabled = False
    settings.langfuse_public_key = "pk"
    settings.langfuse_secret_key = "sk"

    assert isinstance(get_tracer(settings), NoOpTracer)


def test_get_tracer_returns_noop_when_credentials_missing():
    settings = Settings(anthropic_api_key="x")
    settings.observability.langfuse_enabled = True
    settings.langfuse_public_key = None
    settings.langfuse_secret_key = None

    assert isinstance(get_tracer(settings), NoOpTracer)


def test_get_tracer_returns_langfuse_tracer_when_enabled_and_configured():
    settings = Settings(anthropic_api_key="x")
    settings.observability.langfuse_enabled = True
    settings.langfuse_public_key = "pk-fake"
    settings.langfuse_secret_key = "sk-fake"

    tracer = get_tracer(settings)

    assert isinstance(tracer, LangfuseTracer)
    # Constructing a real Langfuse client with fake keys never raises (probe-verified,
    # see Conventions Check) -- no live_langfuse gate needed for this assertion alone.
```

**Step 2 — verify failure**: `ModuleNotFoundError: No module named 'observability.langfuse_tracer'`.

**Step 3 — minimal implementation**:

`src/observability/langfuse_tracer.py`:
```python
from contextlib import contextmanager

from langfuse import Langfuse

from config.settings import Settings
from observability.tracer import NoOpTracer, Tracer


class LangfuseTracer:
    def __init__(self, client: Langfuse):
        self._client = client

    @contextmanager
    def span(self, name: str, *, as_type: str = "span", model: str | None = None):
        with self._client.start_as_current_observation(name=name, as_type=as_type, model=model) as span:
            yield span


def get_tracer(settings: Settings) -> Tracer:
    if not settings.observability.langfuse_enabled:
        return NoOpTracer()
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return NoOpTracer()
    client = Langfuse(public_key=settings.langfuse_public_key, secret_key=settings.langfuse_secret_key)
    return LangfuseTracer(client)
```

**Step 4 — verify pass**: 5 passed.

**Step 5 — commit**: `git add src/observability/langfuse_tracer.py tests/observability/test_langfuse_tracer.py && git commit -m "[Feature] Observability: LangfuseTracer + get_tracer config-driven factory"`

---

### Chunk 7.3 — cost calculator (pure function)

**Files**: Create `src/observability/cost.py`; Create `tests/observability/test_cost.py`; Modify `src/config/settings.py` (`ObservabilityConfig.price_table`); Modify `config.yaml`, `config.example.yaml`.

**Step 1 — failing tests**:
```python
import pytest

from observability.cost import calculate_cost

PRICE_TABLE = {"fake-model": {"input_per_million": 3.0, "output_per_million": 15.0}}


def test_calculate_cost_prices_input_and_output_tokens_independently():
    cost = calculate_cost("fake-model", input_tokens=1_000_000, output_tokens=0, price_table=PRICE_TABLE)
    assert cost == pytest.approx(3.0)

    cost = calculate_cost("fake-model", input_tokens=0, output_tokens=1_000_000, price_table=PRICE_TABLE)
    assert cost == pytest.approx(15.0)


def test_calculate_cost_raises_on_unpriced_model():
    with pytest.raises(KeyError, match="fake-model"):
        calculate_cost("fake-model", input_tokens=100, output_tokens=100, price_table={})
```

**Step 2 — verify failure**: `ModuleNotFoundError: No module named 'observability.cost'`.

**Step 3 — minimal implementation**:

`src/observability/cost.py`:
```python
def calculate_cost(
    model: str, input_tokens: int, output_tokens: int, price_table: dict[str, dict[str, float]]
) -> float:
    if model not in price_table:
        raise KeyError(f"No price entry for model '{model}' in observability.price_table")
    prices = price_table[model]
    return (input_tokens * prices["input_per_million"] + output_tokens * prices["output_per_million"]) / 1_000_000
```

`src/config/settings.py` (`ObservabilityConfig`, extend):
```python
class ObservabilityConfig(BaseModel):
    langfuse_enabled: bool = True
    daily_cost_cap_usd: float = 5.0
    cost_db_path: str = "data/daily_cost.sqlite3"
    price_table: dict[str, dict[str, float]] = {
        # Placeholder figures -- verify against Anthropic's current published pricing
        # before trusting Chunk 7.6's real cost capture (Decision 5).
        "claude-sonnet-5": {"input_per_million": 3.0, "output_per_million": 15.0},
        "claude-haiku-4-5-20251001": {"input_per_million": 1.0, "output_per_million": 5.0},
    }
```

`config.yaml` / `config.example.yaml` (`observability:` section, extend in lockstep — Config Template Sync):
```yaml
observability:
  langfuse_enabled: true
  daily_cost_cap_usd: 5.0
  cost_db_path: data/daily_cost.sqlite3
  price_table:
    claude-sonnet-5:
      input_per_million: 3.0
      output_per_million: 15.0
    claude-haiku-4-5-20251001:
      input_per_million: 1.0
      output_per_million: 5.0
```

**Step 4 — verify pass**: 2 passed (plus full suite still green — confirms `ObservabilityConfig`'s new fields don't break any existing `Settings()` construction).

**Step 5 — commit**: `git add src/observability/cost.py tests/observability/test_cost.py src/config/settings.py config.yaml config.example.yaml && git commit -m "[Feature] Observability: pure cost calculator + config-driven price table"`

---

### Chunk 7.4 — daily running cost total (sqlite) + budget check

**Files**: Create `src/observability/daily_cost.py`; Create `tests/observability/test_daily_cost.py`.

**Step 1 — failing tests**:
```python
from observability.daily_cost import check_budget, get_daily_total, record_cost


def test_record_cost_accumulates_same_day_calls(tmp_path):
    db_path = tmp_path / "daily_cost.sqlite3"

    total = record_cost(db_path, 1.50, day="2026-07-15")
    assert total == 1.50

    total = record_cost(db_path, 0.75, day="2026-07-15")
    assert total == 2.25

    assert get_daily_total(db_path, day="2026-07-15") == 2.25


def test_get_daily_total_is_zero_for_a_day_with_no_recorded_cost(tmp_path):
    db_path = tmp_path / "daily_cost.sqlite3"
    assert get_daily_total(db_path, day="2026-07-15") == 0.0


def test_a_new_day_starts_a_fresh_total(tmp_path):
    db_path = tmp_path / "daily_cost.sqlite3"
    record_cost(db_path, 4.00, day="2026-07-14")

    assert get_daily_total(db_path, day="2026-07-15") == 0.0
    assert get_daily_total(db_path, day="2026-07-14") == 4.00


def test_check_budget_true_only_once_cap_is_exceeded(tmp_path):
    db_path = tmp_path / "daily_cost.sqlite3"
    record_cost(db_path, 4.00, day="2026-07-15")

    assert check_budget(db_path, cap_usd=5.0, day="2026-07-15") is False

    record_cost(db_path, 1.50, day="2026-07-15")

    assert check_budget(db_path, cap_usd=5.0, day="2026-07-15") is True
```

**Step 2 — verify failure**: `ModuleNotFoundError: No module named 'observability.daily_cost'`.

**Step 3 — minimal implementation**:

`src/observability/daily_cost.py`:
```python
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS daily_cost (
    day TEXT PRIMARY KEY,
    total_usd REAL NOT NULL
)
"""


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(_CREATE_TABLE)
    return conn


def record_cost(db_path: Path, cost_usd: float, day: str | None = None) -> float:
    day = day or _today()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT total_usd FROM daily_cost WHERE day = ?", (day,)).fetchone()
        new_total = (row[0] if row else 0.0) + cost_usd
        conn.execute(
            "INSERT OR REPLACE INTO daily_cost (day, total_usd) VALUES (?, ?)", (day, new_total)
        )
    return new_total


def get_daily_total(db_path: Path, day: str | None = None) -> float:
    day = day or _today()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT total_usd FROM daily_cost WHERE day = ?", (day,)).fetchone()
    return row[0] if row else 0.0


def check_budget(db_path: Path, cap_usd: float, day: str | None = None) -> bool:
    """True once today's running total exceeds cap_usd. Caller decides what to do (Decision 3: warn, never block)."""
    return get_daily_total(db_path, day) > cap_usd
```

**Step 4 — verify pass**: 4 passed.

**Step 5 — commit**: `git add src/observability/daily_cost.py tests/observability/test_daily_cost.py && git commit -m "[Feature] Observability: sqlite daily running cost total + budget check"`

---

### Chunk 7.5 — `ObservabilityContext` + `report_usage`

**Files**: Create `src/observability/context.py`; Create `src/observability/usage.py`; Create `tests/observability/test_usage.py`.

**Step 1 — failing tests**:
```python
import logging

from config.settings import ObservabilityConfig
from observability.daily_cost import get_daily_total
from observability.usage import report_usage

PRICE_TABLE = {"fake-model": {"input_per_million": 3.0, "output_per_million": 15.0}}


def test_report_usage_records_cost_to_the_daily_total(tmp_path):
    config = ObservabilityConfig(
        cost_db_path=str(tmp_path / "daily_cost.sqlite3"), price_table=PRICE_TABLE, daily_cost_cap_usd=100.0
    )

    cost = report_usage("fake-model", input_tokens=1_000_000, output_tokens=0, config=config)

    assert cost == 3.0
    assert get_daily_total(tmp_path / "daily_cost.sqlite3") == 3.0


def test_report_usage_warns_and_returns_zero_for_an_unpriced_model(tmp_path, caplog):
    config = ObservabilityConfig(cost_db_path=str(tmp_path / "daily_cost.sqlite3"), price_table={})

    with caplog.at_level(logging.WARNING):
        cost = report_usage("unpriced-model", input_tokens=100, output_tokens=100, config=config)

    assert cost == 0.0
    assert "unpriced-model" in caplog.text


def test_report_usage_warns_without_raising_when_daily_cap_exceeded(tmp_path, caplog):
    config = ObservabilityConfig(
        cost_db_path=str(tmp_path / "daily_cost.sqlite3"), price_table=PRICE_TABLE, daily_cost_cap_usd=1.0
    )

    with caplog.at_level(logging.WARNING):
        cost = report_usage("fake-model", input_tokens=1_000_000, output_tokens=0, config=config)

    assert cost == 3.0  # the call that pushed spend over the cap still succeeds and returns its real cost
    assert "cap" in caplog.text.lower()
```

**Step 2 — verify failure**: `ModuleNotFoundError: No module named 'observability.usage'`.

**Step 3 — minimal implementation**:

`src/observability/context.py`:
```python
from dataclasses import dataclass

from config.settings import ObservabilityConfig
from observability.tracer import NoOpTracer, Tracer


@dataclass
class ObservabilityContext:
    tracer: Tracer
    config: ObservabilityConfig


def noop_observability() -> ObservabilityContext:
    return ObservabilityContext(tracer=NoOpTracer(), config=ObservabilityConfig())
```

`src/observability/usage.py`:
```python
import logging

from config.settings import ObservabilityConfig
from observability.cost import calculate_cost
from observability.daily_cost import check_budget, record_cost

logger = logging.getLogger(__name__)


def report_usage(model: str, input_tokens: int, output_tokens: int, config: ObservabilityConfig) -> float:
    """Prices a real API call and records it to the daily running total. Never raises --
    an unpriced model or an over-budget day must not break the caller's real work (Decision 4)."""
    try:
        cost = calculate_cost(model, input_tokens, output_tokens, config.price_table)
    except KeyError as e:
        logger.warning(str(e))
        return 0.0

    total = record_cost(config.cost_db_path, cost)
    if check_budget(config.cost_db_path, config.daily_cost_cap_usd):
        logger.warning(
            f"Daily cost cap exceeded: ${total:.2f} spent today (cap ${config.daily_cost_cap_usd:.2f})"
        )
    return cost
```

**Step 4 — verify pass**: 3 passed.

**Step 5 — commit**: `git add src/observability/context.py src/observability/usage.py tests/observability/test_usage.py && git commit -m "[Feature] Observability: ObservabilityContext bundle + report_usage entry point"`

---

### Chunk 7.6 — wire `generate_answer` (Block 4) and `verify_citations` (Block 5) leaf functions only

**Note on ordering**: this chunk wires the two *leaf* generation functions only — it does not yet touch `answer_question`/`answer_with_verified_citations`'s bodies. Those orchestrators call `hybrid_retrieve`/`rerank` too, and those don't accept an `observability` parameter until Chunk 7.8 — threading the orchestrators before then would reference a keyword argument that doesn't exist yet. Orchestrator threading is its own chunk (7.8), after every leaf function it calls accepts the parameter.

**Files**: Modify `src/generate/client.py`, `src/citations/verify.py`; Modify `tests/generate/test_client.py`, `tests/citations/test_verify.py`.

**Step 1 — failing test** (representative — same shape added to both `test_client.py` and `test_verify.py`; uses a fake `Tracer`/`SpanHandle` double, no real Langfuse):
```python
# tests/generate/test_client.py -- new test alongside existing ones
from observability.context import ObservabilityContext
from observability.tracer import NoOpTracer


class SpyTracer:
    def __init__(self):
        self.spans = []

    def span(self, name, *, as_type="span", model=None):
        self.spans.append({"name": name, "as_type": as_type, "model": model})
        return _SpySpanCtx()


class _SpySpanCtx:
    def __enter__(self):
        class _Handle:
            def update(self, **kwargs):
                pass
        return _Handle()

    def __exit__(self, *exc):
        return False


def test_generate_answer_opens_a_generation_span(make_fake_structured_client):
    # (fake client returns a GeneratedAnswer + .usage, per the existing FakeClient
    #  pattern in this file -- extended with a `.usage` attribute on the fake response)
    ...
    tracer = SpyTracer()
    observability = ObservabilityContext(tracer=tracer, config=ObservabilityConfig(price_table={}))

    generate_answer(client, "q", [("a", "text")], config, observability=observability)

    assert tracer.spans == [{"name": "generate.answer", "as_type": "generation", "model": config.model}]


def test_generate_answer_defaults_to_noop_tracer_when_observability_omitted(make_fake_structured_client):
    # existing calls with no `observability` argument must keep working unmodified
    result = generate_answer(client, "q", [("a", "text")], config)
    assert result.answer_text  # unchanged behavior, no tracer required
```

**Step 2 — verify failure**: `TypeError: generate_answer() got an unexpected keyword argument 'observability'`.

**Step 3 — minimal implementation**:

`src/generate/client.py` (diff):
```python
from observability.context import ObservabilityContext, noop_observability
from observability.usage import report_usage


def generate_answer(
    client, question: str, chunks: list[tuple[str, str]], config: GenerationConfig,
    observability: ObservabilityContext | None = None,
) -> GeneratedAnswer:
    if not chunks:
        return GeneratedAnswer(answer_text=NO_CONTEXT_ANSWER, citations=[])

    observability = observability or noop_observability()
    scoped_client = client.with_options(max_retries=config.max_retries, timeout=config.timeout_seconds)
    prompt = build_prompt(question, chunks)
    with observability.tracer.span("generate.answer", as_type="generation", model=config.model) as span:
        try:
            response = scoped_client.messages.parse(
                model=config.model, max_tokens=config.max_tokens, thinking={"type": "disabled"},
                messages=[{"role": "user", "content": prompt}], output_format=GeneratedAnswer,
            )
        except ValidationError as e:
            raise RuntimeError(
                f"Anthropic response could not be parsed as GeneratedAnswer, likely because "
                f"it was truncated by max_tokens (currently {config.max_tokens}). "
                f"Consider raising generation.max_tokens."
            ) from e
        cost = report_usage(
            config.model, response.usage.input_tokens, response.usage.output_tokens, observability.config
        )
        span.update(
            usage_details={"input": response.usage.input_tokens, "output": response.usage.output_tokens},
            cost_details={"total": cost},
        )
    return response.parsed_output
```

`src/citations/verify.py` gets the identical shape: `observability: ObservabilityContext | None = None` param, `observability = observability or noop_observability()`, wraps the existing `scoped_client.messages.parse(...)` in `observability.tracer.span("citations.verify", as_type="generation", model=config.judge_model)`, calls `report_usage(config.judge_model, ...)` and `span.update(...)` the same way. (The empty-citations short-circuit at the top of `verify_citations` returns before ever touching `observability` — no span for a call that never hit the API, matching `generate_answer`'s empty-chunks short-circuit.)

**Step 4 — verify pass**: existing `generate`/`citations` suites stay green (untouched call sites use the default), new span-assertion tests pass.

**Step 5 — commit**: `git add src/generate/client.py src/citations/verify.py tests/generate/test_client.py tests/citations/test_verify.py && git commit -m "[Feature] Observability: trace generate_answer + verify_citations leaf calls"`

---

### Chunk 7.7 — wire `hybrid_retrieve` (3 spans) and `rerank` (1 span)

**Files**: Modify `src/retrieval/hybrid.py`, `src/rerank/cross_encoder.py`; Modify `tests/retrieval/test_hybrid.py`, `tests/rerank/test_cross_encoder.py`.

**Step 1 — failing test** (representative, `hybrid_retrieve`):
```python
def test_hybrid_retrieve_opens_three_spans_for_bm25_vector_fusion(tmp_path):
    # existing real-index fixture setup (mirrors this file's existing slow-marked tests)
    tracer = SpyTracer()
    observability = ObservabilityContext(tracer=tracer, config=ObservabilityConfig())

    hybrid_retrieve(bm25_dir, vector_db_path, "stall", config, observability=observability)

    assert [s["name"] for s in tracer.spans] == [
        "retrieval.bm25.search", "retrieval.vector.search", "retrieval.fusion.rrf"
    ]
```

**Step 2 — verify failure**: `TypeError: hybrid_retrieve() got an unexpected keyword argument 'observability'`.

**Step 3 — minimal implementation**:

`src/retrieval/hybrid.py`:
```python
from observability.context import ObservabilityContext, noop_observability


def hybrid_retrieve(
    bm25_index_dir: Path, vector_db_path: Path, query: str, config: RetrievalConfig,
    observability: ObservabilityContext | None = None,
) -> list[str]:
    observability = observability or noop_observability()
    tracer = observability.tracer

    with tracer.span("retrieval.bm25.search"):
        bm25_index, corpus_ids = load_bm25_index(bm25_index_dir)
        bm25_ranking = search_bm25(bm25_index, corpus_ids, query, top_k=config.top_n)
    with tracer.span("retrieval.vector.search"):
        vector_ranking = search_vector(vector_db_path, query, top_k=config.top_n)
    with tracer.span("retrieval.fusion.rrf"):
        fused = reciprocal_rank_fusion(
            [bm25_ranking, vector_ranking], weights=[config.bm25_weight, config.vector_weight], k=config.rrf_k
        )
    return fused[: config.top_n]
```

`src/rerank/cross_encoder.py`'s `rerank` gains the same optional `observability` param, wraps its existing scoring body in one `tracer.span("rerank.score")`; the existing `enabled=False` passthrough returns before ever touching `observability` (unchanged — no span for a no-op call).

**Step 4 — verify pass**: existing retrieval/rerank suites stay green; new span-order assertions pass.

**Step 5 — commit**: `git add src/retrieval/hybrid.py src/rerank/cross_encoder.py tests/retrieval/test_hybrid.py tests/rerank/test_cross_encoder.py && git commit -m "[Feature] Observability: trace hybrid_retrieve's bm25/vector/fusion steps and rerank"`

---

### Chunk 7.8 — thread one shared `ObservabilityContext` through the orchestrators (Decision 6)

**Note on ordering**: only buildable now — every leaf function this touches (`hybrid_retrieve`, `rerank`, `generate_answer`, `verify_citations`) already accepts `observability` as of Chunks 7.6-7.7. This is the chunk where "one live query produces one nested trace" actually becomes true, by constructing exactly one `ObservabilityContext` at the top of the call chain and passing the *same* instance all the way down.

**Files**: Modify `src/generate/pipeline.py`, `src/citations/pipeline.py`; Modify `tests/generate/test_pipeline.py`, `tests/citations/test_pipeline.py`.

**Step 1 — failing test** (representative, `answer_question`):
```python
def test_answer_question_passes_one_shared_observability_context_to_every_stage(monkeypatch):
    calls = []

    def fake_hybrid_retrieve(bm25_dir, vector_db_path, question, config, observability=None):
        calls.append(("hybrid_retrieve", observability))
        return ["a"]

    def fake_rerank(question, candidates, config, observability=None):
        calls.append(("rerank", observability))
        return [cid for cid, _ in candidates]

    def fake_generate_answer(client, question, chunks, config, observability=None):
        calls.append(("generate_answer", observability))
        return GeneratedAnswer(answer_text="x", citations=[])

    monkeypatch.setattr(pipeline, "hybrid_retrieve", fake_hybrid_retrieve)
    monkeypatch.setattr(pipeline, "rerank", fake_rerank)
    monkeypatch.setattr(pipeline, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(pipeline, "get_chunk_texts", lambda db, ids: {cid: "text" for cid in ids})

    given = ObservabilityContext(tracer=NoOpTracer(), config=ObservabilityConfig())
    answer_question("q", client=object(), bm25_dir=Path("x"), vector_db_path=Path("x"),
                     settings=Settings(anthropic_api_key="x"), observability=given)

    assert [c[1] for c in calls] == [given, given, given]  # same instance, not three separate ones
```

**Step 2 — verify failure**: `TypeError: answer_question() got an unexpected keyword argument 'observability'`.

**Step 3 — minimal implementation**:
```python
# generate/pipeline.py
def answer_question(
    question: str, client, bm25_dir: Path, vector_db_path: Path, settings: Settings,
    observability: ObservabilityContext | None = None,
) -> GeneratedAnswer:
    observability = observability or noop_observability()
    top_n_ids = hybrid_retrieve(bm25_dir, vector_db_path, question, settings.retrieval, observability=observability)
    texts = get_chunk_texts(vector_db_path, top_n_ids) if top_n_ids else {}
    top_k_ids = rerank(question, [(cid, texts[cid]) for cid in top_n_ids], settings.rerank, observability=observability)
    chunks = [(cid, texts[cid]) for cid in top_k_ids]
    return generate_answer(client, question, chunks, settings.generation, observability=observability)


# citations/pipeline.py
def answer_with_verified_citations(
    question: str, client, bm25_dir: Path, vector_db_path: Path, settings: Settings
) -> VerifiedAnswer:
    observability = ObservabilityContext(tracer=get_tracer(settings), config=settings.observability)
    answer = answer_question(question, client, bm25_dir, vector_db_path, settings, observability=observability)
    chunk_texts = get_chunk_texts(vector_db_path, answer.citations) if answer.citations else {}
    return verify_citations(client, question, answer, chunk_texts, settings.citations, observability=observability)
```

**Step 4 — verify pass**: existing `generate`/`citations` pipeline suites stay green (no caller passes `observability` today); new same-instance-threading assertion passes.

**Step 5 — commit**: `git add src/generate/pipeline.py src/citations/pipeline.py tests/generate/test_pipeline.py tests/citations/test_pipeline.py && git commit -m "[Feature] Observability: thread one shared ObservabilityContext through the query-time orchestrators"`

---

### Chunk 7.9 — wire `call_structured_judge` (cost only, per Decision 2)

**Files**: Modify `src/eval/llm_call.py`, `src/eval/judge.py`, `src/eval/relevance.py`; Modify `tests/eval/test_judge.py`, `tests/eval/test_relevance.py`.

**Step 1 — failing test**:
```python
# tests/eval/test_judge.py -- new test
from config.settings import ObservabilityConfig
from observability.daily_cost import get_daily_total


def test_judge_answer_records_cost_when_observability_config_given(make_fake_structured_client, tmp_path):
    client = make_fake_structured_client(parsed_output=AnswerJudgment(correct=True, complete=True, reasoning="x"))
    obs_config = ObservabilityConfig(
        cost_db_path=str(tmp_path / "daily_cost.sqlite3"),
        price_table={"claude-haiku-4-5-20251001": {"input_per_million": 1.0, "output_per_million": 5.0}},
    )

    judge_answer(client, "q", "a", "notes", EvalConfig(), observability_config=obs_config)

    assert get_daily_total(tmp_path / "daily_cost.sqlite3") > 0.0


def test_judge_answer_defaults_to_no_cost_tracking_when_observability_config_omitted(make_fake_structured_client):
    client = make_fake_structured_client(parsed_output=AnswerJudgment(correct=True, complete=True, reasoning="x"))
    result = judge_answer(client, "q", "a", "notes", EvalConfig())  # unchanged existing call shape
    assert result.correct is True
```

(`make_fake_structured_client`'s `FakeResponse` needs a `.usage` attribute added — a `Usage(input_tokens=.., output_tokens=..)`-shaped stub — so `call_structured_judge` has something real to report; extending the shared fixture in `tests/eval/conftest.py`.)

**Step 2 — verify failure**: `TypeError: judge_answer() got an unexpected keyword argument 'observability_config'`.

**Step 3 — minimal implementation**:

`src/eval/llm_call.py` (diff):
```python
from config.settings import ObservabilityConfig
from observability.usage import report_usage


def call_structured_judge(
    client, prompt: str, output_format: type[BaseModel], config: EvalConfig, error_label: str,
    observability_config: ObservabilityConfig | None = None,
) -> BaseModel:
    scoped_client = client.with_options(max_retries=config.judge_max_retries, timeout=config.judge_timeout_seconds)
    try:
        response = scoped_client.messages.parse(
            model=config.judge_model, max_tokens=config.judge_max_tokens, temperature=config.judge_temperature,
            thinking={"type": "disabled"}, messages=[{"role": "user", "content": prompt}], output_format=output_format,
        )
    except ValidationError as e:
        raise RuntimeError(
            f"{error_label} response could not be parsed, likely truncated by "
            f"eval.judge_max_tokens (currently {config.judge_max_tokens})."
        ) from e
    if observability_config is not None:
        report_usage(config.judge_model, response.usage.input_tokens, response.usage.output_tokens, observability_config)
    return response.parsed_output
```

`judge_answer`/`label_relevance` each gain the same `observability_config: ObservabilityConfig | None = None` passthrough param, forwarded to `call_structured_judge` unchanged — no other body changes.

**Step 4 — verify pass**: existing eval-judge tests stay green (no `observability_config` passed → skipped, matches Decision 2's "cost tracking only, and only when given" — no default construction of a real sqlite path in every judge call unless a caller actually wants tracking).

**Step 5 — commit**: `git add src/eval/llm_call.py src/eval/judge.py src/eval/relevance.py tests/eval/test_judge.py tests/eval/test_relevance.py tests/eval/conftest.py && git commit -m "[Feature] Observability: cost-track eval judges via call_structured_judge (no spans, per Decision 2)"`

---

### Chunk 7.10 — real end-to-end trace verification (`live_langfuse`-gated, currently BLOCKED)

**Files**: Modify `tests/conftest.py` (register `live_langfuse` marker, mirrors the existing `live_api` skip-gate); Create `tests/observability/test_live_trace.py`.

**Blocked on**: the user creating a free Langfuse Cloud project and populating `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` in `.env` (both currently empty — confirmed Chunk 7.0). Do not attempt this chunk until that's done; every other chunk in this block is fully buildable and testable without it.

**Step 1 — failing test** (written now, run only once credentials exist):
```python
import os
import pytest

from citations.pipeline import answer_with_verified_citations
from config.settings import Settings


@pytest.mark.slow
@pytest.mark.live_langfuse
def test_a_real_query_produces_one_nested_trace_in_langfuse():
    settings = Settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    answer_with_verified_citations(
        "What's the difference between VMC and VSO?", client,
        Path("data/bm25_index"), Path("data/vector_db"), settings,
    )
    # Manual verification step (no public Langfuse query API assumed): open the Langfuse
    # Cloud dashboard and confirm one trace with nested bm25/vector/fusion/rerank/
    # generate.answer/citations.verify spans, usage/cost visible on the two generation spans.
```

**Step 2-5**: deferred until unblocked — do not write `tests/conftest.py`'s marker registration or run this chunk until real credentials exist.

## Technical Debt Strategy

- **Price table placeholders** (Decision 5) must be corrected against Anthropic's real current pricing before Chunk 7.6's cost numbers are trusted for anything beyond "the mechanism works." Log to `BUGS.md` at build time if not corrected in the same session.
- **`hybrid_retrieve`/`rerank`/`generate_answer`/`verify_citations`/`call_structured_judge` all gain one more optional parameter each** (5 already-shipped, already-audited functions across Blocks 2-6 touched this block) — every touch is additive-optional with a safe default (Decision 1), but this is still real signature growth worth naming explicitly at `/audit` time, not just at `/plan` time.
- **No CLI command surfaces the daily cost total or triggers a real query end-to-end yet** — that's Block 8's `query`/`eval` CLI commands. This block only builds the plumbing; nothing calls `answer_with_verified_citations` for a live user query until Block 8 exists.
- **`report_usage`'s cost-cap warning has no test proving it's ever actually seen by a human** (it's a `logging.warning`, not surfaced to a CLI user or a Langfuse dashboard alert) — acceptable for this block's scope (design doc says "surfaced as a budget-runaway signal," not "surfaced to a specific UI"), revisit if Block 8's CLI wants to print it directly.
