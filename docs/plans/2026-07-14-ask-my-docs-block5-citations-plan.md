# Block 5 Implementation Plan — Citation Verification

**Date**: 2026-07-14
**Parent plan**: `2026-07-11-ask-my-docs-implementation-plan.md` (Block 5 sketch)
**Design doc**: `2026-07-10-ask-my-docs-design.md`

## Header

- **Goal**: Given a `GeneratedAnswer` (Block 4's `{answer_text, citations: [chunk_id]}`) and the cited chunks' text, verify each citation actually supports the answer — strip unsupported ones, score `coverage`, and flag `low_confidence` below a config threshold (never block the answer).
- **Architecture**: `src/citations/prompt.py` (versioned judge template + builder) → `src/citations/schema.py` (judge output contract + public `VerifiedAnswer`) → `src/citations/verify.py` (`verify_citations`, the only function that touches the Anthropic API for this block) → `src/citations/pipeline.py` (`answer_with_verified_citations`, wraps Block 4's already-shipped `answer_question` — does not modify it).
- **Design patterns**: Same structured-output pattern as Block 4 (`client.messages.parse(..., output_format=...)`), SDK-native retry/timeout, `thinking` disabled. **New this block**: the judge call is *batched* — one Haiku call scores every citation in an answer at once (a `list[CitationVerdict]` structured output), not one call per citation. Empty-citations short-circuit (mirrors Block 4's empty-context short-circuit): zero citations → `coverage=1.0`, `low_confidence=False`, zero API calls.
- **Tech stack**: `anthropic` SDK (existing dependency), judge model `claude-haiku-4-5-20251001` (matches `eval.judge_model`'s already-current default), CPU-only elsewhere unaffected.

## Conventions Check (per `/plan` workflow)

- **Reuse audit**: `CitationConfig` (`src/config/settings.py`) and `config.yaml`'s `citations:` section already exist with `low_confidence_threshold: 0.7` — added speculatively during Block 0, never consumed until now. `GeneratedAnswer` (`src/generate/schema.py`) is the input contract; unchanged by this block. `get_chunk_texts` (`src/ingest/vector_index.py`) is the only chunk-text fetch function — reused, not reimplemented (see Decision 3 on the resulting second fetch). No existing verification/judge-calling code exists anywhere in `src/` — `src/citations/__init__.py` is an empty placeholder package from the original repo scaffold.
- **Test style**: pytest, `@pytest.mark.live_api` (existing marker, already registered in `pyproject.toml`, skipped unless `RUN_LIVE_API_TESTS=1`) for the real-judge-call tests — no new marker needed, Block 4 already paid this setup cost.
- **Config-isolation check**: all new `citations.*` fields (`judge_model`, `judge_temperature`, `max_tokens`, `max_retries`, `timeout_seconds`) are infra constants, not corpus facts — same category as `generation.*`, safe to construct directly in tests via `CitationConfig(...)`, no repo `config.yaml` isolation risk.
- **Third-party API to verify with a throwaway script before RED** (build.md step 2): confirm `client.messages.parse(model=..., max_tokens=..., temperature=..., thinking={"type": "disabled"}, output_format=PydanticModelWithAListField)` works for a **nested-list** structured-output shape (`VerificationResult.verdicts: list[CitationVerdict]`) — Block 4 only probed a flat model (`GeneratedAnswer`). Also confirm `temperature` is accepted alongside `thinking: disabled` (untested combination so far). Run once real credentials exist (they already do, from Block 4) — a few cents.
- **Probe-verified fixture requirement**: Chunk 5.4's live-judge tests need a discrimination fixture the same way Block 2/3/4 did — one citation whose chunk text clearly supports the answer, one whose chunk text is off-topic relative to the answer, run once against the real API, actual verdicts logged in a comment before the assertion is finalized.

### Decisions made at plan time (not deferred to build)

1. **Faithfulness check is a Haiku LLM-judge, batched into one call per answer, not one call per citation.** Per the user's explicit choice over a local NLI cross-encoder or reusing the rerank score: an LLM read catches nuanced cases (e.g., the answer overstates what a chunk actually says) that a lexical/entailment-only model would miss, and it's consistent with this project's existing "haiku for judges" stack decision. Batching (one call, `output_format=VerificationResult` wrapping `list[CitationVerdict]`) instead of N sequential per-citation calls keeps latency to one round-trip regardless of citation count (typically ≤ `rerank.top_k` = 5) and is cheaper than N calls with per-call overhead. Rejected: per-citation calls — no accuracy benefit here, strictly worse latency/cost.
2. **New `CitationConfig` fields (`judge_model`, `judge_temperature`, `max_tokens`, `max_retries`, `timeout_seconds`) are separate from `EvalConfig`'s `judge_model`/`judge_temperature`, even though both default to the same Haiku model.** `eval.judge_model` grades golden-dataset answer quality in Block 6's batch eval harness; `citations.judge_model` fires on every live query to check faithfulness — different call sites likely to need independent tuning (e.g., a stricter judge_temperature or a different model if one drifts). Accepted duplication of the default string, not unified. Logged to `BUGS.md` as a reconsideration point if the two ever need identical behavior.
3. **`citations/pipeline.py` fetches chunk text for the cited subset a second time, rather than changing `generate.pipeline.answer_question`'s return contract to also expose its internal texts dict.** `answer_question` is an already-shipped, audited Block 4 function; widening its return type for an internal efficiency gain (re-fetching ≤5 ids is cheap next to the judge's own API round-trip) isn't worth touching and retesting it. Mirrors Block 3→4's own precedent (the "double text fetch" note deferred to whichever block actually needed the change). Logged to `BUGS.md` for reconsideration if Block 7's serving layer wants a single fetch across a whole request.
4. **A judge verdict missing for a cited chunk_id (or naming a chunk_id that wasn't asked about) defaults that citation to unsupported.** Fail-safe: the guarantee this block exists to provide is "every remaining citation is judge-confirmed," so an incomplete/malformed verdict list must strip, never silently keep. Tested explicitly (Chunk 5.3) — this is exactly the untested-guard bug class Block 3 and Block 4's audits both found in other spots.
5. **Disable extended thinking for the judge call too.** Same reasoning as Block 4's generation call — a short per-citation classification task doesn't need adaptive thinking; every skipped thinking token is a real cost saving.
6. **Scope limit, stated explicitly (not a build-time surprise): this block verifies only the citations the model already listed, not uncited claims in `answer_text`.** The design doc's "LLM-judge/NLI per claim" phrasing could be read as full claim-level faithfulness checking; that would require claim segmentation (splitting `answer_text` into individual assertions) — materially bigger scope than what Block 4's `{answer_text, citations}` contract supports today. Per-citation verification (does this cited chunk support *something* in the answer) is what's built; a truly uncited hallucinated sentence is not caught by this block. Logged to `BUGS.md` as a known limitation, not silently scoped down.

## Block 5: Citation Verification

**Success criteria**

- [ ] `CitationVerdict`/`VerificationResult` (judge output) and `VerifiedAnswer` (public result: `answer_text`, `citations`, `coverage`, `low_confidence`) schemas exist.
- [ ] Judge prompt is versioned (`prompts/verify_v1.md`, `PROMPT_VERSION` constant), instructs per-citation supported/unsupported judgment grounded only in the given excerpt.
- [ ] Empty citations → `verify_citations` returns `coverage=1.0`, `low_confidence=False`, zero API calls (asserted via an exploding client).
- [ ] Real judge call: batched structured output, SDK-native retry/timeout, thinking disabled — asserted via a fake client capturing `with_options`/`parse` kwargs.
- [ ] Missing/unexpected chunk_ids in the verdict list default to unsupported — asserted via a fake client returning an incomplete verdict list.
- [ ] Malformed/truncated judge output raises a clear `RuntimeError` naming `citations.max_tokens`, not a raw `pydantic.ValidationError`.
- [ ] Live-judge test: one clearly-supported citation is kept, one clearly-unrelated citation is stripped and lowers `coverage` (probe-verified fixture).
- [ ] `answer_with_verified_citations` orchestrator composes `answer_question` → `verify_citations`, fetching cited-subset text only when citations is non-empty.
- [ ] Real-corpus spot-check: run the 8 design-doc sample questions end-to-end through the full verified pipeline; record `coverage`/`low_confidence` per question, confirm the honest non-answer (question 8) still yields `coverage=1.0` with zero judge calls, confirm at least one real case where an unsupported citation gets stripped (or note if none occurred and why).

---

### Chunk 5.1 — schemas + versioned judge prompt template (no API calls)

**Files**: Create `prompts/verify_v1.md`; Create `src/citations/schema.py`; Create `src/citations/prompt.py`; Create `tests/citations/test_prompt.py`.

**Step 1 — failing tests**:

```python
from citations.prompt import PROMPT_VERSION, build_verify_prompt


def test_build_verify_prompt_embeds_question_answer_and_chunk_ids():
    citations = [("abc123", "Stalls occur when the critical angle of attack is exceeded.")]

    prompt = build_verify_prompt(
        "What causes a stall?",
        "A stall occurs when the critical angle of attack is exceeded [abc123].",
        citations,
    )

    assert "What causes a stall?" in prompt
    assert "abc123" in prompt
    assert "critical angle of attack is exceeded" in prompt


def test_build_verify_prompt_instructs_per_citation_support_judgment():
    prompt = build_verify_prompt("any question", "any answer", [("id1", "some text")])

    assert "support" in prompt.lower()


def test_prompt_version_is_exposed():
    assert PROMPT_VERSION == "verify_v1"
```

```python
from citations.schema import CitationVerdict, VerificationResult, VerifiedAnswer


def test_verified_answer_holds_answer_citations_coverage_and_flag():
    result = VerifiedAnswer(answer_text="...", citations=["a"], coverage=1.0, low_confidence=False)

    assert result.citations == ["a"]
    assert result.coverage == 1.0
    assert result.low_confidence is False


def test_verification_result_wraps_a_list_of_verdicts():
    result = VerificationResult(verdicts=[CitationVerdict(chunk_id="a", supported=True)])

    assert result.verdicts[0].chunk_id == "a"
    assert result.verdicts[0].supported is True
```

(Both test files can live in `tests/citations/test_prompt.py` and `tests/citations/test_schema.py` respectively — split by module under test, matching `tests/generate/`'s layout.)

**Step 2 — verify failure**: `uv run pytest tests/citations -q` → `ModuleNotFoundError: No module named 'citations.prompt'` (then `citations.schema` once the first is created).

**Step 3 — minimal implementation**:

`prompts/verify_v1.md`:
```markdown
You are checking whether excerpts from the FAA Airplane Flying Handbook actually support an answer that was already generated from them. For each excerpt below, decide whether it directly supports a claim made in the answer — mark `supported: true` only if the excerpt itself substantiates something the answer states. Mark `supported: false` if the excerpt is irrelevant, only tangentially related, or contradicts the answer. Judge each excerpt independently, using only that excerpt's own text.

Question: {question}

Answer: {answer_text}

Excerpts:
{context}

Return exactly one verdict for every chunk id listed above.
```

`src/citations/prompt.py`:
```python
from pathlib import Path

PROMPT_VERSION = "verify_v1"
_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / f"{PROMPT_VERSION}.md"


def build_verify_prompt(question: str, answer_text: str, citations: list[tuple[str, str]]) -> str:
    template = _TEMPLATE_PATH.read_text()
    context = "\n\n".join(f"[{chunk_id}] {text}" for chunk_id, text in citations)
    return template.format(question=question, answer_text=answer_text, context=context)
```

`src/citations/schema.py`:
```python
from pydantic import BaseModel


class CitationVerdict(BaseModel):
    chunk_id: str
    supported: bool


class VerificationResult(BaseModel):
    verdicts: list[CitationVerdict]


class VerifiedAnswer(BaseModel):
    answer_text: str
    citations: list[str]
    coverage: float
    low_confidence: bool
```

**Step 4 — verify pass**: `uv run pytest tests/citations -q` → 5 passed. Full suite green.

**Step 5 — commit**: `git add prompts/verify_v1.md src/citations/prompt.py src/citations/schema.py tests/citations/ && git commit -m "[Feature] Citations: judge prompt template and verification schemas"`

---

### Chunk 5.2 — `CitationConfig` fields + empty-citations short-circuit (no API calls)

**Files**: Modify `src/config/settings.py` (`CitationConfig`); Modify `config.yaml`; Modify `config.example.yaml`; Create `src/citations/verify.py`; Create `tests/citations/test_verify.py`.

**Step 1 — failing test**:

```python
import pytest

from citations.schema import VerifiedAnswer
from citations.verify import verify_citations
from config.settings import CitationConfig
from generate.schema import GeneratedAnswer


def test_no_citations_returns_full_coverage_without_calling_client():
    class ExplodingClient:
        def __getattr__(self, name):
            pytest.fail("must not touch the Anthropic client when there are no citations")

    answer = GeneratedAnswer(answer_text="I don't have information about that.", citations=[])
    config = CitationConfig()

    result = verify_citations(ExplodingClient(), "any question", answer, {}, config)

    assert isinstance(result, VerifiedAnswer)
    assert result.citations == []
    assert result.coverage == 1.0
    assert result.low_confidence is False
```

**Step 2 — verify failure**: `uv run pytest tests/citations -q` → `ModuleNotFoundError: No module named 'citations.verify'`.

**Step 3 — minimal implementation**:

`CitationConfig` (Decision 2):
```python
class CitationConfig(BaseModel):
    low_confidence_threshold: float = 0.7
    judge_model: str = "claude-haiku-4-5-20251001"
    judge_temperature: float = 0.0
    max_tokens: int = 1024
    max_retries: int = 3
    timeout_seconds: float = 30.0
```

`config.yaml` and `config.example.yaml`, `citations:` section (keep both in sync in this commit — the Block 4 audit's "Config Template Sync" checklist item exists precisely because this drifted once already):
```yaml
citations:
  low_confidence_threshold: 0.7
  judge_model: claude-haiku-4-5-20251001
  judge_temperature: 0.0
  max_tokens: 1024
  max_retries: 3
  timeout_seconds: 30.0
```

`src/citations/verify.py`:
```python
from citations.schema import VerifiedAnswer
from config.settings import CitationConfig
from generate.schema import GeneratedAnswer


def verify_citations(
    client,
    question: str,
    answer: GeneratedAnswer,
    chunk_texts: dict[str, str],
    config: CitationConfig,
) -> VerifiedAnswer:
    if not answer.citations:
        return VerifiedAnswer(
            answer_text=answer.answer_text, citations=[], coverage=1.0, low_confidence=False
        )
    raise NotImplementedError  # real judge call lands in Chunk 5.3
```

**Step 4 — verify pass**: `uv run pytest tests/citations -q` → 1 passed (`NotImplementedError` path not hit). Full suite green.

**Step 5 — commit**: `git add src/citations/verify.py tests/citations/test_verify.py src/config/settings.py config.yaml config.example.yaml && git commit -m "[Feature] Citations: config fields; empty-citations short-circuit never calls the API"`

---

### Chunk 5.3 — real judge call: batched structured output, missing-verdict fail-safe, bounded retry/timeout

**Pre-step (build.md step 2)**: throwaway script (scratchpad, not committed) — call `client.messages.parse(model="claude-haiku-4-5-20251001", max_tokens=1024, temperature=0.0, thinking={"type": "disabled"}, messages=[...], output_format=VerificationResult)` against the real API. Confirm the nested-list structured-output shape (`verdicts: list[CitationVerdict]`) parses correctly and that `temperature` is accepted alongside `thinking: disabled` (neither combination was probed in Block 4, which only used a flat model and no explicit `temperature`).

**Files**: Modify `src/citations/verify.py`; Modify `tests/citations/test_verify.py`.

**Step 1 — failing tests**:

```python
from citations.schema import CitationVerdict, VerificationResult


def test_verify_citations_configures_client_and_strips_unsupported():
    verdicts = VerificationResult(
        verdicts=[
            CitationVerdict(chunk_id="abc123", supported=True),
            CitationVerdict(chunk_id="off999", supported=False),
        ]
    )

    class FakeMessages:
        def __init__(self):
            self.parse_kwargs = None

        def parse(self, **kwargs):
            self.parse_kwargs = kwargs

            class FakeResponse:
                parsed_output = verdicts

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
    config = CitationConfig(
        judge_model="claude-haiku-4-5-20251001",
        judge_temperature=0.0,
        max_tokens=777,
        max_retries=5,
        timeout_seconds=9.0,
    )
    answer = GeneratedAnswer(
        answer_text="A stall occurs when critical AoA is exceeded [abc123].",
        citations=["abc123", "off999"],
    )
    chunk_texts = {"abc123": "Stalls occur at critical AoA.", "off999": "The Wings program..."}

    result = verify_citations(client, "What causes a stall?", answer, chunk_texts, config)

    assert client.with_options_kwargs == {"max_retries": 5, "timeout": 9.0}
    parse_kwargs = client.scoped.messages.parse_kwargs
    assert parse_kwargs["model"] == "claude-haiku-4-5-20251001"
    assert parse_kwargs["max_tokens"] == 777
    assert parse_kwargs["temperature"] == 0.0
    assert parse_kwargs["thinking"] == {"type": "disabled"}
    assert parse_kwargs["output_format"] is VerificationResult
    assert result.citations == ["abc123"]
    assert result.coverage == 0.5
    assert result.low_confidence is True  # 0.5 < default threshold 0.7


def test_verify_citations_treats_missing_verdict_as_unsupported():
    # Judge only returned a verdict for one of two cited chunks - the missing one
    # must default to unsupported (fail-safe), not silently kept.
    verdicts = VerificationResult(verdicts=[CitationVerdict(chunk_id="abc123", supported=True)])

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

    answer = GeneratedAnswer(answer_text="...", citations=["abc123", "missing999"])
    chunk_texts = {"abc123": "text a", "missing999": "text b"}

    result = verify_citations(FakeClient(), "q", answer, chunk_texts, CitationConfig())

    assert result.citations == ["abc123"]
    assert result.coverage == 0.5


def test_verify_citations_raises_clear_error_on_truncated_output():
    class FakeMessages:
        def parse(self, **kwargs):
            VerificationResult.model_validate_json('{"verdicts": [{"chunk_id": "a')  # raises

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    answer = GeneratedAnswer(answer_text="...", citations=["a"])
    config = CitationConfig(max_tokens=50)

    with pytest.raises(RuntimeError, match="max_tokens"):
        verify_citations(FakeClient(), "q", answer, {"a": "text"}, config)
```

**Step 2 — verify failure**: `uv run pytest tests/citations -q` → `NotImplementedError`.

**Step 3 — minimal implementation** (replace the `raise`):

```python
from pydantic import ValidationError

from citations.prompt import build_verify_prompt
from citations.schema import VerificationResult


def verify_citations(
    client,
    question: str,
    answer: GeneratedAnswer,
    chunk_texts: dict[str, str],
    config: CitationConfig,
) -> VerifiedAnswer:
    if not answer.citations:
        return VerifiedAnswer(
            answer_text=answer.answer_text, citations=[], coverage=1.0, low_confidence=False
        )

    scoped_client = client.with_options(max_retries=config.max_retries, timeout=config.timeout_seconds)
    excerpts = [(cid, chunk_texts[cid]) for cid in answer.citations]
    prompt = build_verify_prompt(question, answer.answer_text, excerpts)
    try:
        response = scoped_client.messages.parse(
            model=config.judge_model,
            max_tokens=config.max_tokens,
            temperature=config.judge_temperature,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
            output_format=VerificationResult,
        )
    except ValidationError as e:
        raise RuntimeError(
            f"Anthropic judge response could not be parsed as VerificationResult, likely "
            f"because it was truncated by max_tokens (currently {config.max_tokens}). "
            f"Consider raising citations.max_tokens."
        ) from e

    verdicts = {v.chunk_id: v.supported for v in response.parsed_output.verdicts}
    supported = [cid for cid in answer.citations if verdicts.get(cid, False)]
    coverage = len(supported) / len(answer.citations)
    return VerifiedAnswer(
        answer_text=answer.answer_text,
        citations=supported,
        coverage=coverage,
        low_confidence=coverage < config.low_confidence_threshold,
    )
```

**Step 4 — verify pass**: `uv run pytest tests/citations -q` → 4 passed. Full suite green.

**Step 5 — commit**: `git add src/citations/verify.py tests/citations/test_verify.py && git commit -m "[Feature] Citations: batched judge call strips unsupported citations, fails safe on missing verdicts"`

---

### Chunk 5.4 — real judge test (slow, gated, probe-verified)

**Files**: Modify `tests/citations/test_verify.py`.

**Step 1 — failing/new tests**:

```python
import anthropic

from config.settings import Settings


@pytest.mark.slow
@pytest.mark.live_api
def test_verify_citations_keeps_supported_and_strips_unsupported_on_real_judge():
    client = anthropic.Anthropic(api_key=Settings().anthropic_api_key)
    config = CitationConfig()
    answer = GeneratedAnswer(
        answer_text="A stall occurs when the wing exceeds its critical angle of attack [stall001].",
        citations=["stall001", "unrelated1"],
    )
    chunk_texts = {
        "stall001": "A stall occurs when the wing exceeds its critical angle of attack, "
        "causing a sudden loss of lift.",
        "unrelated1": "The FAA Wings Program offers recurrent training credit.",
    }

    result = verify_citations(client, "What causes a stall?", answer, chunk_texts, config)

    assert "stall001" in result.citations
    assert "unrelated1" not in result.citations
    assert result.coverage < 1.0
```

**Step 2 — verify**: run once with `RUN_LIVE_API_TESTS=1 uv run pytest tests/citations -q -m live_api`. Record the actual verdicts observed in a comment above the test (probe-verification, per Block 2/3/4 convention) — if the judge doesn't discriminate on this fixture, strengthen the unrelated distractor rather than weakening the assertion.

**Step 3/4 — verify**: full suite `uv run pytest -q` (live_api tests skipped by default, 0 warnings); `RUN_LIVE_API_TESTS=1 uv run pytest -q -m live_api` → passes (Block 4's + Block 5's live tests both run).

**Step 5 — commit**: `git add tests/citations/test_verify.py && git commit -m "[Test] Citations: real-judge support/strip correctness"`

---

### Chunk 5.5 — `answer_with_verified_citations` orchestrator

**Files**: Create `src/citations/pipeline.py`; Create `tests/citations/test_pipeline.py`.

**Step 1 — failing tests** (fast — monkeypatch every sub-stage):

```python
from pathlib import Path

from citations import pipeline
from citations.pipeline import answer_with_verified_citations
from citations.schema import VerifiedAnswer
from config.settings import Settings
from generate.schema import GeneratedAnswer


def test_answer_with_verified_citations_fetches_cited_subset_and_verifies(monkeypatch):
    def fake_answer_question(question, client, bm25_dir, vector_db_path, settings):
        return GeneratedAnswer(answer_text="Stalls happen when...", citations=["b"])

    calls = {"get_chunk_texts": 0}

    def fake_get_chunk_texts(vector_db_path, chunk_ids):
        calls["get_chunk_texts"] += 1
        assert chunk_ids == ["b"]
        return {"b": "text b"}

    captured = {}

    def fake_verify_citations(client, question, answer, chunk_texts, config):
        captured["chunk_texts"] = chunk_texts
        return VerifiedAnswer(answer_text=answer.answer_text, citations=["b"], coverage=1.0, low_confidence=False)

    monkeypatch.setattr(pipeline, "answer_question", fake_answer_question)
    monkeypatch.setattr(pipeline, "get_chunk_texts", fake_get_chunk_texts)
    monkeypatch.setattr(pipeline, "verify_citations", fake_verify_citations)

    settings = Settings(anthropic_api_key="placeholder")

    result = answer_with_verified_citations(
        "q", client=object(), bm25_dir=Path("unused"), vector_db_path=Path("unused"), settings=settings
    )

    assert calls["get_chunk_texts"] == 1
    assert captured["chunk_texts"] == {"b": "text b"}
    assert result.citations == ["b"]


def test_answer_with_verified_citations_skips_text_fetch_when_no_citations(monkeypatch):
    def fake_answer_question(question, client, bm25_dir, vector_db_path, settings):
        return GeneratedAnswer(answer_text="I don't have information about that.", citations=[])

    def exploding_get_chunk_texts(vector_db_path, chunk_ids):
        raise AssertionError("must not fetch chunk text when there are no citations to verify")

    captured = {}

    def fake_verify_citations(client, question, answer, chunk_texts, config):
        captured["chunk_texts"] = chunk_texts
        return VerifiedAnswer(answer_text=answer.answer_text, citations=[], coverage=1.0, low_confidence=False)

    monkeypatch.setattr(pipeline, "answer_question", fake_answer_question)
    monkeypatch.setattr(pipeline, "get_chunk_texts", exploding_get_chunk_texts)
    monkeypatch.setattr(pipeline, "verify_citations", fake_verify_citations)

    settings = Settings(anthropic_api_key="placeholder")

    result = answer_with_verified_citations(
        "q", client=object(), bm25_dir=Path("unused"), vector_db_path=Path("unused"), settings=settings
    )

    assert captured["chunk_texts"] == {}
    assert result.citations == []
```

**Step 2 — verify failure**: `ModuleNotFoundError: No module named 'citations.pipeline'`.

**Step 3 — minimal implementation**:

```python
from pathlib import Path

from citations.schema import VerifiedAnswer
from citations.verify import verify_citations
from config.settings import Settings
from generate.pipeline import answer_question
from ingest.vector_index import get_chunk_texts


def answer_with_verified_citations(
    question: str, client, bm25_dir: Path, vector_db_path: Path, settings: Settings
) -> VerifiedAnswer:
    answer = answer_question(question, client, bm25_dir, vector_db_path, settings)
    chunk_texts = get_chunk_texts(vector_db_path, answer.citations) if answer.citations else {}
    return verify_citations(client, question, answer, chunk_texts, settings.citations)
```

**Step 4 — verify pass**: `uv run pytest tests/citations -q` → passes. Full suite green.

**Step 5 — commit**: `git add src/citations/pipeline.py tests/citations/test_pipeline.py && git commit -m "[Feature] Citations: answer_with_verified_citations composes generation and verification"`

---

### Chunk 5.6 — real end-to-end spot-check (manual, no new tests)

**Files**: none committed (throwaway script in scratchpad); findings go to `BUGS.md` (if any), `PROJECT_HISTORY.md`, `LEARNING_NOTES.md`.

1. Run `answer_with_verified_citations` against the real handbook indexes for all 8 design-doc sample questions.
2. For each: record `answer_text`, `citations` (post-verification), `coverage`, `low_confidence`, and spot-read whether the surviving citations genuinely support the answer.
3. Confirm question 8 (out-of-scope helicopter autorotation) still yields the honest non-answer with `coverage=1.0`, `low_confidence=False`, and zero judge API calls (verify via logging or a debugger breakpoint, not just the output shape).
4. Confirm question 3 (short-field vs. soft-field takeoff — the known Block 4 retrieval-surfacing gap, deferred to Block 6) behaves sanely under verification: its citations should still be judged supported for the half-answer it does give, `coverage` should not itself be the signal that catches the missing-half problem (that's still Block 6's job) — just confirm this block doesn't mask or worsen the known gap.
5. Record per-query added latency/cost from the judge call (on top of Block 4's generation cost) — first real signal on whether Block 7's daily-cost-cap needs the extra judge call accounted for.
6. Log findings; check off Block 5's success criteria in this file.

---

## Technical Debt Strategy (log to `BUGS.md` at build time if accepted)

- This block verifies only listed citations, not full per-claim faithfulness (Decision 6) — an uncited hallucinated sentence in `answer_text` is not caught. A full fix needs claim segmentation, which is bigger scope than Block 4's current `{answer_text, citations}` contract supports; revisit if the design doc's "LLM-judge/NLI per claim" language is meant literally.
- `citations.judge_model`/`judge_temperature` duplicate `eval.judge_model`/`judge_temperature`'s default value without sharing config (Decision 2) — acceptable now, reconsider if the two judges are ever meant to move in lockstep.
- `citations/pipeline.py` re-fetches chunk text for the cited subset instead of reusing Block 4's internal texts dict (Decision 3) — cheap at current citation counts (≤5), revisit at Block 7 if the serving layer wants a single fetch per request.
- No prompt-injection defense on the judge prompt beyond "context comes from our own corpus" — same acceptance as Block 4.

## Production Standards (P0)

- **Timeout Mapping**: `citations.timeout_seconds` (default 30.0) passed via `client.with_options(timeout=...)` — same pattern as Block 4.
- **Error Handling**: judge API errors (`RateLimitError`, `APIStatusError`, etc.) propagate uncaught, same as Block 4 — SDK-native bounded retry is the mitigation; final-failure structured-error/metric wiring is Block 7's job.
- **Loading States**: N/A (no UI).
- **Live-Service Test Gate**: `@pytest.mark.live_api`, skipped unless `RUN_LIVE_API_TESTS=1` — reuses Block 4's existing gate, no new pytest config needed.
