# Block 4 Implementation Plan — Grounded Generation

**Date**: 2026-07-13
**Parent plan**: `2026-07-11-ask-my-docs-implementation-plan.md` (Block 4 sketch, line ~1532)
**Design doc**: `2026-07-10-ask-my-docs-design.md`

## Header

- **Goal**: Given a question and the reranked top-k chunks, produce a structured `{answer_text, citations: [chunk_id]}` via the Anthropic API — grounded in provided context only, honest about insufficient context, bounded-retry on API errors.
- **Architecture**: `src/generate/prompt.py` (versioned template + builder) → `src/generate/schema.py` (structured-output contract) → `src/generate/client.py` (`generate_answer`, the only function that touches the Anthropic API) → `src/generate/pipeline.py` (`answer_question`, the retrieve→rerank→generate orchestrator this block owes per the Block 3 plan). Nothing upstream changes.
- **Design patterns**: Structured outputs via `client.messages.parse(..., output_format=GeneratedAnswer)` — the API validates the citation-list shape server-side, so there's no hand-written JSON parsing to get wrong. Retry/timeout are SDK-native (`client.with_options(max_retries=..., timeout=...)`), not hand-rolled — the SDK already does exponential backoff on 429/5xx. Empty-context short-circuit (no chunks → canned answer, zero API calls) mirrors Block 3's disabled-passthrough pattern: a cost-relevant branch that must be provably unreachable-to-the-API, not just "usually doesn't call it."
- **Tech stack**: `anthropic` SDK (already a dependency, `>=0.116.0`), model `claude-sonnet-5` (see Decision 1 below), CPU-only elsewhere unaffected.

## Conventions Check (per `/plan` workflow)

- **Reuse audit**: `hybrid_retrieve` returns `list[str]` ids (`src/retrieval/hybrid.py`). `rerank()` takes `(chunk_id, text)` pairs and returns `list[str]` ids (`src/rerank/cross_encoder.py`) — it does **not** return text, so the caller needs chunk text twice (once to build rerank candidates, once to build the generation prompt). `get_chunk_texts` (`src/ingest/vector_index.py`) is the only text-fetch function and already returns a `dict[chunk_id, text]`. **Decision 2** (below) resolves the Block 3 debt note ("double fetch") by having the orchestrator fetch texts once for the top-n candidates and reuse that same dict to build the top-k generation prompt — no second DB query, no change to `rerank`'s contract. `GenerationConfig` and `CitationConfig` already exist in `settings.py` and `config.yaml` already carries a `generation:` section, but see Decision 1 and Decision 3 for required field changes.
- **Test style**: pytest, `@pytest.mark.slow` for real-model/real-index tests (existing convention). **New**: `@pytest.mark.live_api` for tests that call the real Anthropic API and spend money — this is the first block to touch a paid API, and the Block 1 plan explicitly deferred this gate here ("Live-Service Test Gate... owed to Block 4"). Registered in `pyproject.toml`; skipped by default unless `RUN_LIVE_API_TESTS=1` is set (Chunk 4.0).
- **Config-isolation check**: `generation.model`/`max_tokens`/`max_retries`/`timeout_seconds` are infra constants, not corpus facts — no test isolation risk (same category as `rerank.model`, already safely read in tests via direct `GenerationConfig(...)` construction, never the repo's `config.yaml`).
- **Third-party API to verify with a throwaway script before RED** (build.md step 2): `client.messages.parse(model=..., max_tokens=..., messages=[...], output_format=PydanticModel)` — confirm `response.parsed_output` is the validated instance (per the claude-api skill reference) and confirm structured outputs work with `thinking={"type": "disabled"}` set simultaneously (Decision 4). Run this against the real API once real credentials exist (Chunk 4.0 prerequisite) — costs a few cents, acceptable one-time probe cost per the project's cost-control philosophy.
- **Probe-verified fixture requirement**: Chunk 4.4's live-API test fixtures (an in-scope question with real chunk text, an irrelevant-context case) should be run once and the actual response logged in a comment, same as Block 2/3's discrimination fixtures — LLM output isn't exactly reproducible, so assertions must be loose (e.g., "citations is a subset of the given ids", not "citations == [...]").

### Decisions made at plan time (not deferred to build)

1. **Model default is stale — fix to `claude-sonnet-5`.** `GenerationConfig.model` and `config.yaml`'s `generation.model` both currently read `"claude-sonnet-4-5"`, a name that predates this session's model catalog (current: `claude-sonnet-5`, per Anthropic's model list). Both already carry a "verify against current Anthropic model list at build time" comment — Chunk 4.1 is that verification. `eval.judge_model` (`claude-haiku-4-5-20251001`) is already current; no change needed there.
2. **Reuse the pre-rerank texts dict for the post-rerank prompt — don't re-fetch or change `rerank`'s contract.** `rerank`'s top-n candidates already require `get_chunk_texts` for the full top-n set before scoring; since `rerank`'s output ids are a subset of its input ids, the orchestrator (Chunk 4.5) looks up the top-k ids in the *same* dict rather than calling `get_chunk_texts` again. Zero code change to `rerank`, zero double DB fetch. Rejected: changing `rerank` to return `(id, text)` pairs — would touch a function Block 3 already shipped and tested for no behavioral gain.
3. **Add `max_tokens` and `timeout_seconds` to `GenerationConfig`; drop `backoff_base_seconds`.** The design doc's "bounded retry (3 attempts, backoff)" and "30s timeout" are satisfied by the SDK's own retry/timeout machinery (`client.with_options(max_retries=..., timeout=...)`) — the SDK already does exponential backoff on 429/5xx, so a hand-rolled `backoff_base_seconds` would be dead configuration (the exact "unused parameter" bug class the 2026-07-13 audit already found once this session in `min_tokens`/RRF). `max_tokens` (short answers with citations; default 1024, config-driven per CLAUDE.md's no-magic-numbers rule) and `timeout_seconds` (default 30.0, per the design doc's "heavy AI operation" 30s guidance, owed to this block since Block 1) are genuinely new needed values, so they're added instead.
4. **Disable extended thinking for this task.** `claude-sonnet-5` runs adaptive thinking by default when `thinking` is omitted — unnecessary latency/cost for a short extraction-and-cite task (no multi-step reasoning). Set `thinking={"type": "disabled"}` explicitly. Rejected: leaving the default (adaptive) — this is exactly the kind of unexamined cost-adder the project's daily-cost-cap design pillar exists to catch; a citation task doesn't need it and every skipped thinking token is a real per-query cost saving over the life of the eval harness.
5. **Insufficient-context is two distinct paths, tested two different ways.** (a) *No chunks retrieved at all* → `generate_answer` short-circuits before any API call and returns a canned `GeneratedAnswer` deterministically — this is a pure-function contract, unit-testable without mocking the model. (b) *Chunks retrieved but don't answer the question* → the model itself must recognize this and return empty `citations` — this is LLM behavior, not a deterministic contract, so it's covered by the live-API test (loosely) and the real-corpus spot-check (design doc's sample question 8: "Does this handbook cover helicopter autorotation procedures?").

## Block 4: Grounded Generation

**Success criteria** (verified at build time, 2026-07-13)
- [x] Prompt instructs "answer only from provided context, cite by chunk_id"; template is versioned (`prompts/answer_v1.md`, a `PROMPT_VERSION` constant exposed for future Langfuse/eval attribution).
- [x] Empty/no retrieved chunks → `generate_answer` returns an honest "I don't have that" answer without calling the Anthropic API (asserted via a client that fails the test if called).
- [x] Chunks present but off-topic → model returns `citations: []` (live-API test; required a prompt fix — see Chunk 4.4 — confirmed again at the real-corpus spot-check with the design doc's out-of-scope sample question).
- [x] Bounded retry + timeout: `generate_answer` constructs the client with `max_retries=config.max_retries` and `timeout=config.timeout_seconds` (asserted via a fast test capturing the `with_options` call — no real API needed for this assertion).
- [x] `answer_question` orchestrator composes retrieve → rerank → generate, reusing one `get_chunk_texts` fetch (no second DB query for the same ids).
- [x] Real-corpus spot-check: ran all 8 design-doc sample questions end-to-end. Citations resolve to real chunk_ids on 7/8; question 8 (out-of-scope) yields an honest non-answer with empty citations. Question 6 crashed on first run (`max_tokens=1024` too low for a detailed answer, truncating structured JSON) — fixed via TDD (clear `RuntimeError`, `max_tokens` raised to 2048) and re-verified. Question 3 (short-field vs. soft-field takeoff) answered only half the comparison — a retrieval/rerank surfacing gap, logged to `BUGS.md` as input for Block 6's golden dataset, not fixed in this block. Per-query latency logged (8–30s, dominated by generation for longer answers); per-query token cost not captured — `generate_answer` discards `response.usage`, logged as a Block 7 debt item.

---

### Chunk 4.0 — prerequisite: real `ANTHROPIC_API_KEY` + live-API test gate

**Blocking**: Chunks 4.3 onward call the real Anthropic API. Per memory, only a placeholder key exists (`.env` doesn't exist yet, only `.env.example`). **Resume-here checkpoint if this session ends before a real key is available**: Chunks 4.1–4.2 (prompt + schema + empty-context contract) need no API access and can be built regardless.

**Files**: Modify `pyproject.toml`; Create `tests/conftest.py` addition (skip hook) — or a small `tests/generate/conftest.py` if scoping the hook to one test dir is cleaner at build time.

1. Get a real `ANTHROPIC_API_KEY` into `.env` (user action, not committed — `.env` is gitignored).
2. Register the marker in `pyproject.toml`:
   ```toml
   markers = [
       "slow: local-model tests, skip with -m 'not slow' for the fast dev loop",
       "live_api: hits the real Anthropic API and costs money; skip by default, run with RUN_LIVE_API_TESTS=1",
   ]
   ```
3. Add a `pytest_collection_modifyitems` hook (or a simpler autouse fixture) that skips `live_api`-marked tests unless `os.environ.get("RUN_LIVE_API_TESTS") == "1"`.
4. Verify: `uv run pytest -q` (no `live_api` tests exist yet, so this is a no-op check that the marker registers without warnings) → all green, zero warnings about unknown marks.
5. Commit: `git add pyproject.toml tests/ && git commit -m "[Feature] Test: gate real-Anthropic-API tests behind RUN_LIVE_API_TESTS"`

---

### Chunk 4.1 — versioned prompt template + `build_prompt`

**Files**: Create `prompts/answer_v1.md`; Create `src/generate/prompt.py`; Create `tests/generate/test_prompt.py`; Modify `src/config/settings.py` (Decision 1: `model: str = "claude-sonnet-5"`); Modify `config.yaml` (same).

**Step 1 — failing tests**:

```python
from generate.prompt import PROMPT_VERSION, build_prompt


def test_build_prompt_embeds_question_and_chunk_ids():
    chunks = [("abc123", "Stalls occur when the critical angle of attack is exceeded.")]

    prompt = build_prompt("What causes a stall?", chunks)

    assert "What causes a stall?" in prompt
    assert "abc123" in prompt
    assert "Stalls occur when" in prompt


def test_build_prompt_instructs_context_only_and_citation_by_id():
    prompt = build_prompt("any question", [("id1", "some text")])

    assert "cite" in prompt.lower()
    assert "only" in prompt.lower()  # "answer only from the provided context"


def test_prompt_version_is_exposed():
    assert PROMPT_VERSION == "answer_v1"
```

**Step 2 — verify failure**: `uv run pytest tests/generate -q` → `ModuleNotFoundError: No module named 'generate.prompt'`.

**Step 3 — minimal implementation**:

`prompts/answer_v1.md`:
```markdown
You are answering questions about the FAA Airplane Flying Handbook using only the excerpts provided below. Cite every claim by its chunk id in square brackets, e.g. [abc123]. If the excerpts do not contain enough information to answer, say so honestly instead of guessing — do not use outside knowledge.

Question: {question}

Excerpts:
{context}
```

`src/generate/prompt.py`:
```python
from pathlib import Path

PROMPT_VERSION = "answer_v1"
_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / f"{PROMPT_VERSION}.md"


def build_prompt(question: str, chunks: list[tuple[str, str]]) -> str:
    template = _TEMPLATE_PATH.read_text()
    context = "\n\n".join(f"[{chunk_id}] {text}" for chunk_id, text in chunks)
    return template.format(question=question, context=context)
```

Also apply Decision 1 in the same commit: `src/config/settings.py:GenerationConfig.model = "claude-sonnet-5"`, `config.yaml`'s `generation.model: claude-sonnet-5`.

**Step 4 — verify pass**: `uv run pytest tests/generate -q` → 3 passed. Full suite: `uv run pytest -q` → all green (config default change shouldn't break anything; nothing reads `generation.model` yet).

**Step 5 — commit**: `git add prompts/ src/generate/prompt.py tests/generate/test_prompt.py src/config/settings.py config.yaml && git commit -m "[Feature] Generate: versioned prompt template; fix stale generation.model default"`

---

### Chunk 4.2 — `GeneratedAnswer` schema + empty-context contract (no API calls)

**Files**: Create `src/generate/schema.py`; Create `src/generate/client.py`; Create `tests/generate/test_client.py`; Modify `src/config/settings.py` (Decision 3: add `max_tokens`, `timeout_seconds`; drop `backoff_base_seconds`).

**Step 1 — failing tests** (fast — no client needed for the empty-chunks path):

```python
import pytest

from config.settings import GenerationConfig
from generate.client import generate_answer
from generate.schema import GeneratedAnswer


def test_empty_chunks_returns_canned_answer_without_calling_client():
    class ExplodingClient:
        def __getattr__(self, name):
            pytest.fail("must not touch the Anthropic client when there are no chunks")

    config = GenerationConfig()

    result = generate_answer(ExplodingClient(), "any question", [], config)

    assert isinstance(result, GeneratedAnswer)
    assert result.citations == []
    assert "don't have" in result.answer_text.lower()
```

**Step 2 — verify failure**: `uv run pytest tests/generate -q` → `ModuleNotFoundError: No module named 'generate.client'`.

**Step 3 — minimal implementation**:

`src/generate/schema.py`:
```python
from pydantic import BaseModel


class GeneratedAnswer(BaseModel):
    answer_text: str
    citations: list[str]
```

`src/generate/client.py`:
```python
from generate.prompt import build_prompt
from generate.schema import GeneratedAnswer
from config.settings import GenerationConfig

_NO_CONTEXT_ANSWER = "I don't have information about that in this handbook."


def generate_answer(
    client, question: str, chunks: list[tuple[str, str]], config: GenerationConfig
) -> GeneratedAnswer:
    if not chunks:
        return GeneratedAnswer(answer_text=_NO_CONTEXT_ANSWER, citations=[])
    raise NotImplementedError  # real API call lands in Chunk 4.3
```

`GenerationConfig` (Decision 3):
```python
class GenerationConfig(BaseModel):
    model: str = "claude-sonnet-5"
    max_tokens: int = 1024
    max_retries: int = 3
    timeout_seconds: float = 30.0
```

(Remove `backoff_base_seconds` from both `settings.py` and `config.yaml`'s `generation:` section — dead config per Decision 3.)

**Step 4 — verify pass**: `uv run pytest tests/generate -q` → 1 passed (the `NotImplementedError` path isn't hit by this test). Full suite green.

**Step 5 — commit**: `git add src/generate/schema.py src/generate/client.py tests/generate/test_client.py src/config/settings.py config.yaml && git commit -m "[Feature] Generate: structured-answer schema; empty-context short-circuit never calls the API"`

---

### Chunk 4.3 — real API call: structured output, bounded retry, timeout, thinking disabled

**Pre-step (build.md step 2)**: throwaway script (scratchpad, not committed) — call `client.messages.parse(model="claude-sonnet-5", max_tokens=1024, thinking={"type": "disabled"}, messages=[...], output_format=GeneratedAnswer)` against the real API once (needs Chunk 4.0's real key). Confirm `response.parsed_output` is a validated `GeneratedAnswer` and that `thinking: disabled` + structured outputs are compatible (no 400).

**Files**: Modify `src/generate/client.py`; Modify `tests/generate/test_client.py`.

**Step 1 — failing tests**:

```python
def test_generate_answer_configures_client_with_retry_and_timeout(monkeypatch):
    captured = {}

    class FakeResponse:
        parsed_output = GeneratedAnswer(answer_text="Stalls happen when...", citations=["abc123"])

    class FakeScopedClient:
        def messages_parse(self, **kwargs):
            captured["parse_kwargs"] = kwargs
            return FakeResponse()

        # matches client.messages.parse(...) call shape
        class messages:
            @staticmethod
            def parse(**kwargs):
                captured["parse_kwargs"] = kwargs
                return FakeResponse()

    class FakeClient:
        def with_options(self, **kwargs):
            captured["with_options_kwargs"] = kwargs
            return FakeScopedClient()

    config = GenerationConfig(model="claude-sonnet-5", max_tokens=999, max_retries=7, timeout_seconds=12.0)

    result = generate_answer(FakeClient(), "What causes a stall?", [("abc123", "text")], config)

    assert captured["with_options_kwargs"] == {"max_retries": 7, "timeout": 12.0}
    assert captured["parse_kwargs"]["model"] == "claude-sonnet-5"
    assert captured["parse_kwargs"]["max_tokens"] == 999
    assert captured["parse_kwargs"]["thinking"] == {"type": "disabled"}
    assert captured["parse_kwargs"]["output_format"] is GeneratedAnswer
    assert result.citations == ["abc123"]
```

(Simplify the `FakeClient`/`FakeScopedClient` nesting at build time to whatever's cleanest — the point under test is: `with_options` receives the config's retry/timeout, and `messages.parse` receives the config's model/max_tokens/thinking/output_format.)

**Step 2 — verify failure**: `uv run pytest tests/generate -q` → `NotImplementedError`.

**Step 3 — minimal implementation** (replace the `raise`):

```python
    scoped_client = client.with_options(
        max_retries=config.max_retries, timeout=config.timeout_seconds
    )
    prompt = build_prompt(question, chunks)
    response = scoped_client.messages.parse(
        model=config.model,
        max_tokens=config.max_tokens,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
        output_format=GeneratedAnswer,
    )
    return response.parsed_output
```

**Step 4 — verify pass**: `uv run pytest tests/generate -q` → 2 passed. Full suite green.

**Step 5 — commit**: `git add src/generate/client.py tests/generate/test_client.py && git commit -m "[Feature] Generate: call Claude with structured output, SDK-native retry/timeout, thinking disabled"`

---

### Chunk 4.4 — real API test (slow, gated, probe-verified)

**Files**: Modify `tests/generate/test_client.py`.

**Step 1 — failing/new tests**:

```python
import os

from anthropic import Anthropic


@pytest.mark.slow
@pytest.mark.live_api
def test_generate_answer_cites_real_chunk_for_in_scope_question():
    client = Anthropic()
    config = GenerationConfig()
    chunks = [
        ("stall001", "A stall occurs when the wing exceeds its critical angle of attack, "
                     "causing a sudden loss of lift."),
        ("unrelated1", "The FAA Wings Program offers recurrent training credit."),
    ]

    result = generate_answer(client, "What causes a stall?", chunks, config)

    # Loose assertion — LLM phrasing varies; behavior under test is citation correctness.
    assert "stall001" in result.citations
    assert "unrelated1" not in result.citations


@pytest.mark.slow
@pytest.mark.live_api
def test_generate_answer_admits_insufficient_context_for_off_topic_chunks():
    client = Anthropic()
    config = GenerationConfig()
    chunks = [("wb01", "Weight and balance must be computed before every flight.")]

    result = generate_answer(client, "Does this handbook cover helicopter autorotation?", chunks, config)

    assert result.citations == []
```

**Step 2 — verify**: run once with `RUN_LIVE_API_TESTS=1 uv run pytest tests/generate -q -m live_api`. Record the actual `answer_text`/`citations` observed in a comment above each test (probe-verification, per Block 2/3 convention) — if either assertion doesn't hold on the real model, adjust the fixture (stronger unrelated distractor, or a clearer off-topic question) rather than weakening the assertion.

**Step 3/4 — verify**: full suite `uv run pytest -q` (live_api tests skipped by default, still 0 warnings); `RUN_LIVE_API_TESTS=1 uv run pytest -q -m live_api` → 2 passed.

**Step 5 — commit**: `git add tests/generate/test_client.py && git commit -m "[Test] Generate: real-API citation correctness and insufficient-context behavior"`

---

### Chunk 4.5 — `answer_question` orchestrator (retrieve → rerank → generate)

**Files**: Create `src/generate/pipeline.py`; Create `tests/generate/test_pipeline.py`.

**Step 1 — failing tests** (fast — monkeypatch every sub-stage; the point under test is composition and the single-fetch reuse from Decision 2):

```python
def test_answer_question_reuses_one_text_fetch_for_rerank_and_generation(monkeypatch):
    calls = {"get_chunk_texts": 0}

    def fake_retrieve(*a, **kw):
        return ["a", "b", "c"]

    def fake_get_chunk_texts(*a, **kw):
        calls["get_chunk_texts"] += 1
        return {"a": "text a", "b": "text b", "c": "text c"}

    def fake_rerank(question, candidates, config):
        return ["b"]  # narrows top-n down to top-k

    captured_chunks = {}

    def fake_generate_answer(client, question, chunks, config):
        captured_chunks["chunks"] = chunks
        return GeneratedAnswer(answer_text="...", citations=["b"])

    monkeypatch.setattr(pipeline, "hybrid_retrieve", fake_retrieve)
    monkeypatch.setattr(pipeline, "get_chunk_texts", fake_get_chunk_texts)
    monkeypatch.setattr(pipeline, "rerank", fake_rerank)
    monkeypatch.setattr(pipeline, "generate_answer", fake_generate_answer)

    result = answer_question("q", client=object(), bm25_dir=..., vector_db_path=..., settings=fake_settings)

    assert calls["get_chunk_texts"] == 1  # reused for both rerank input and generation input
    assert captured_chunks["chunks"] == [("b", "text b")]
    assert result.citations == ["b"]
```

(Exact fixture/settings-object shape to be finalized at build time against the real `Settings` model; the assertions that matter are the single fetch count and the reused-dict lookup.)

**Step 2 — verify failure**: `ModuleNotFoundError: No module named 'generate.pipeline'`.

**Step 3 — minimal implementation**:

```python
from pathlib import Path

from config.settings import Settings
from generate.client import generate_answer
from generate.schema import GeneratedAnswer
from ingest.vector_index import get_chunk_texts
from rerank.cross_encoder import rerank
from retrieval.hybrid import hybrid_retrieve


def answer_question(
    question: str, client, bm25_dir: Path, vector_db_path: Path, settings: Settings
) -> GeneratedAnswer:
    top_n_ids = hybrid_retrieve(bm25_dir, vector_db_path, question, settings.retrieval)
    texts = get_chunk_texts(vector_db_path, top_n_ids) if top_n_ids else {}
    top_k_ids = rerank(question, [(cid, texts[cid]) for cid in top_n_ids], settings.rerank)
    chunks = [(cid, texts[cid]) for cid in top_k_ids]
    return generate_answer(client, question, chunks, settings.generation)
```

**Step 4 — verify pass**: `uv run pytest tests/generate -q` → passes. Full suite green.

**Step 5 — commit**: `git add src/generate/pipeline.py tests/generate/test_pipeline.py && git commit -m "[Feature] Generate: answer_question orchestrator composes retrieve, rerank, and generation"`

---

### Chunk 4.6 — real end-to-end spot-check (manual, no new tests)

**Files**: none committed (throwaway script in scratchpad); findings go to `BUGS.md` (if any), `PROJECT_HISTORY.md`, `LEARNING_NOTES.md`.

1. Run `answer_question` against the real handbook indexes for all 8 design-doc sample questions (VMC/VSO, secondary vs. accelerated stall, short- vs. soft-field takeoff, crosswind takeoff errors, three rules of energy control, upset prevention/recovery, FAA Wings Program, helicopter autorotation).
2. For each: record the answer, citations, whether citations resolve to chunks that actually support the claim (spot-read them), and whether question 8 (out-of-scope) yields an honest non-answer with empty citations.
3. Record cost per query (input/output tokens × price) and latency — first real signal on whether the daily-cost-cap design (Block 7) needs tuning.
4. Log findings; check off Block 4's success criteria in this file.

---

## Technical Debt Strategy (log to `BUGS.md` at build time if accepted)

- `answer_question` takes 5 positional-ish parameters (question, client, bm25_dir, vector_db_path, settings) — matches the existing `hybrid_retrieve` signature style, but revisit alongside the open `BUGS.md` item about `chunk_pdf`'s exploded-scalar signature once Block 8 wires the CLI (one config-object convention, decided once).
- The Anthropic `client` is constructed by the caller (not inside `generate_answer`/`answer_question`) — deliberate, so tests inject fakes without any module-level client singleton; Block 8's CLI is where a real `Anthropic()` gets constructed once per process.
- No prompt-injection defense beyond "context comes from our own corpus" — acceptable for a single-corpus portfolio project; would need addressing if this ever ingested untrusted documents.

## Production Standards (P0)

- **Timeout Mapping**: `timeout_seconds` (default 30.0) passed via `client.with_options(timeout=...)` — satisfies the Block 1 IOU.
- **Error Handling**: API errors (`RateLimitError`, `APIStatusError`, etc.) are not caught in this block — they propagate. Bounded retry is the SDK's own `max_retries`; a final failure after retries is a real exception, which is correct per the design doc's "final failure returns a structured error and increments failure_rate" — the structured-error/metric wiring itself is Block 7's (observability) job, not this block's.
- **Loading States**: N/A (no UI).
- **Live-Service Test Gate**: `@pytest.mark.live_api`, skipped unless `RUN_LIVE_API_TESTS=1` — this is the first block whose tests can spend real money, per Chunk 4.0.
