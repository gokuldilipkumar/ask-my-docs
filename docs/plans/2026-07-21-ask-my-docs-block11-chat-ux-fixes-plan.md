# Block 11 Implementation Plan — Chat UX Fixes: Latency & Citation Noise

**Date**: 2026-07-21
**Parent plan**: none — new scope, motivated by the user's first real usage of Block 10's chat interface (real reported latency + inline citation-noise complaints), not sketched in the original 9-block plan.
**Design doc**: `2026-07-10-ask-my-docs-design.md` (no acceptance criterion for this — this is a post-hoc UX fix, not a design-doc gap)

## Header

- **Goal**: Reduce real per-query latency (currently ~30-37s, real-measured) by capping reranker candidate count and cross-encoder input length, and eliminate the generation prompt's inline bracket-citation noise from displayed answers — both changes verified against the real eval harness so neither trades away answer quality silently.
- **Architecture**: two independent tracks in one plan, since both are direct responses to the same real usage session and share one verification mechanism (this project's existing `eval` CLI / golden dataset / baseline comparison).
  - **Track A (latency)**: config-only — reduce `retrieval.top_n` (fewer candidates reach the reranker) and add a new `rerank.max_length` field (caps cross-encoder input length per pair, threaded into `CrossEncoder(...)`).
  - **Track B (citation noise)**: a new versioned prompt (`prompts/answer_v2.md`) that drops the "cite inline in square brackets" instruction from `prompts/answer_v1.md` while keeping the structured `citations` field's contract completely intact — verified via a real live-API test that the model actually stops emitting brackets.
- **Design patterns**: N/A — no new abstractions, both tracks tune/replace existing config and prompt content.
- **Tech stack**: no new dependencies. Reuses the existing `eval` CLI (`--retrieval-only` for cheap/fast iteration, full mode for the one real correctness/completeness check each track needs) as the verification mechanism for both tracks.

## Conventions Check (per `/plan` workflow, adapted per `CLAUDE.md` — no frontend/Supabase steps apply)

- **Reuse audit**: `RerankConfig`/`RetrievalConfig` (`src/config/settings.py`) are already config-driven — no new config *mechanism* needed, only new/changed field values and one new field (`rerank.max_length`). `rerank()`/`_get_model()` (`src/rerank/cross_encoder.py`) are the only two places constructing a `CrossEncoder` — confirmed via `grep -rn "CrossEncoder(" src/`, single call site. `verify_citations`/`prompts/verify_v1.md` (`src/citations/verify.py`) were read in full: the judge already evaluates whether an excerpt supports *any* claim in the whole `answer_text`, never parsing or relying on inline bracket markers to map a specific sentence to a specific chunk — confirmed removing inline brackets requires **zero changes** to `citations/verify.py` or `verify_v1.md`.
- **Composition Cost Audit**: N/A — no new composition of existing pipeline functions.
- **Additive-Parameter Reach Audit**: `_get_model(model_name: str)` (`src/rerank/cross_encoder.py:10`) gains a second parameter (`max_length`). Every existing caller/fake must be updated — listed explicitly so the build doesn't miss one: the real call site `rerank()` (`:27`, `model = _get_model(config.model)`), and five monkeypatched fakes in `tests/rerank/test_cross_encoder.py`: `test_disabled_rerank_preserves_fused_order_and_truncates` (line 10-14, `lambda name: pytest.fail(...)`), `test_empty_candidates_return_empty_without_loading_model` (line 22-26), `test_rerank_loads_the_model_named_in_config` (line 39-41, `fake_get_model(name)`), `test_rerank_opens_one_span_when_scoring` (line 73), `test_disabled_rerank_opens_no_span` (line 84-86). All five currently take one positional arg (`name`); each must accept the new `max_length` parameter (`lambda name, max_length: ...`) or the real call site's two-arg call breaks every one of them at collection/call time, not just the ones that should exercise the new behavior.
- **Predicted-Behavior Claim Check** — two unverified empirical claims here, neither taken as a plan fact without a real check:
  1. *"Removing the inline-citation instruction while keeping the structured `citations`-field contract will make the model stop emitting bracket citations in prose, without breaking the structured field."* A genuine LLM instruction-following claim — this project's own Block 4 history (`build.md`) shows a first prompt draft's citation rule looked correct on its first fixture, then needed a second real fix once a genuinely different real question exposed the gap. Chunk 11.6 verifies this with a live-API test against a real in-scope question, not assumed from the prompt text reading correctly.
  2. *"`retrieval.top_n` 20→10 roughly halves rerank latency"* — `BUGS.md`'s own wording for this ("`retrieval.top_n` 20 → 10 halves it") is an approximation from Block 4, never actually measured on this corpus. **Verified now, cheaply, at plan time**: a real timed single-query probe on the current committed config (`top_n=20`) measured `retrieve=6.95s`, `rerank=12.48s`, `generate_answer=14.57s`, `verify_citations=2.53s` (4 citations), **TOTAL=36.56s** — real numbers, not estimated, captured this session. Chunk 11.0 re-confirms the exact `top_n`/`max_length` speedup ratio for real before any value is committed, rather than trusting the old approximation.
- **A third real finding from this same probe, not previously known**: a second live-API call during this same probe session hit a genuine `anthropic.APITimeoutError` ("Request timed out or interrupted") after retries — `generation.timeout_seconds=30.0` is uncomfortably tight against real observed generation latency (14.57s on the successful call, and evidently sometimes longer). This is a **real reliability risk already present in the shipped chat UI**, separate from this block's actual goal (reducing latency, not just tolerating it) — logged to `BUGS.md` as a related-but-out-of-scope finding, not fixed in this block (raising the timeout doesn't make anything faster, it just tolerates slowness that Track A is trying to eliminate at the source).
- **Config Isolation**: N/A — this block deliberately edits the real `config.yaml`/`config.example.yaml` (not a synthetic test fixture), matching Chunk 9.1's precedent for intentional, revertible-if-needed config changes.
- **Test style**: matches existing `pytest` conventions; `tests/rerank/test_cross_encoder.py`'s existing fake-model pattern for Track A; `tests/generate/test_prompt.py`'s existing content-assertion pattern plus a new `live_api`-gated test for Track B (mirrors `tests/generate/test_client.py`'s existing live-API tests).

### Decisions made at plan time (not deferred to build)

1. **Track A does not touch `rerank.top_k`** (stays 5). `top_k` truncates the *already-scored* ranked list — it doesn't reduce how many candidates the cross-encoder scores, so it has no effect on rerank compute time. Only `top_n` (candidates entering the reranker) and the new `max_length` (compute per candidate) affect latency.
2. **`_get_model`'s cache is re-keyed by `(model_name, max_length)`, not `model_name` alone.** Cheap to do correctly while already touching this function's signature — avoids a latent staleness bug where a config change to `max_length` within one long-running process (e.g., a future multi-tenant server) would silently keep serving a model built with the old `max_length`. Not fixing a live bug (today's usage is one `Settings()` per process, loaded once), but free to get right now rather than leave as a new, avoidable debt item.
3. **Track B creates `prompts/answer_v2.md` and bumps `PROMPT_VERSION = "answer_v2"` in `src/generate/prompt.py`, never edits `answer_v1.md` in place.** Matches this project's existing versioned-prompt convention (`citations/prompt.py`'s `verify_v1`, this file's own `PROMPT_VERSION` mechanism) — keeps prompt attribution in `EvalRunResult`/Langfuse spans accurate for any historical eval run or trace that used `answer_v1`.
4. **Track B does not touch `citations/verify.py` or `prompts/verify_v1.md`.** Confirmed by reading both: the judge verifies "does this excerpt support a claim in the whole `answer_text`," never parses or depends on inline bracket markers. The fix is entirely upstream, at generation-prompt level.
5. **Neither track's final config/prompt value is decided by this plan document — both are decided by a real `eval` run in `/build`, retrieval-only for cheap Track A iteration, one full run for both tracks' final correctness/completeness confirmation.** This plan states starting hypotheses (`top_n=10`, `max_length=256`) but treats them as hypotheses, not commitments — matching Block 9's own precedent (its planned regression demo didn't reproduce as predicted, and the plan/report said so honestly rather than forcing the expected result).
6. **The real `generation.timeout_seconds=30.0` reliability gap found during this plan's own probe is logged to `BUGS.md`, not fixed here.** Raising a timeout tolerates latency; this block's actual goal is removing it at the source. Revisit only if Track A's real latency reduction still leaves generation calls occasionally exceeding 30s.

## Block 11: Chat UX Fixes — Latency & Citation Noise

**Success criteria**

- [ ] A real `eval --retrieval-only` comparison shows the chosen final `retrieval.top_n`/`rerank.max_length` values keep `mean_recall_at_k`/`mean_mrr`/`mean_ndcg` within `eval.tolerance` of the current committed baseline (`mean_recall_at_k=0.616, mean_mrr=0.906, mean_ndcg=0.783`).
- [ ] A real timed query (same method as this plan's own probe) shows a measured latency reduction vs. the real 36.56s baseline captured this session, with the exact new number reported honestly (not assumed from the old "halves it" approximation).
- [ ] A real full `eval` run (judge-scored) shows `correctness_rate`/`completeness_rate` not regressed beyond `eval.tolerance` vs. the current baseline (`correctness_rate=0.875, completeness_rate=0.625`) for **both** tracks' combined changes.
- [ ] A live-API test confirms `answer_text` from `answer_v2` contains no `[hexid]`-shaped bracket patterns for a real in-scope question, while `GeneratedAnswer.citations` is still populated with real chunk ids.
- [ ] `uv run pytest -m "not slow"` and the full suite stay green throughout, including the five updated `_get_model` fakes in `tests/rerank/test_cross_encoder.py`.
- [ ] `config.yaml`/`config.example.yaml` stay in sync (`rerank.max_length` present in both); `BUGS.md`/`.agent/decisions.log`/README updated with the real before/after numbers and the new `generation.timeout_seconds` finding.

---

### Chunk 11.0 — real "before" numbers (already captured at plan time; re-verify in `/build`)

**Files**: no committed files — a throwaway timing script (scratchpad only, mirrors `generate.pipeline.answer_question`'s exact call sequence), same shape used to produce this plan's own header numbers.

**Step 1 — re-run for real at build time**: re-run the same real single-query timing probe (`hybrid_retrieve` → `get_chunk_texts` → `rerank` → `generate_answer` → `get_chunk_texts` (cited) → `verify_citations`, each stage wrapped in `time.perf_counter()`) against the real committed `data/index/` and current `config.yaml`, to reconfirm this plan's own captured numbers still hold (`retrieve=6.95s, rerank=12.48s, generate=14.57s, verify=2.53s, TOTAL=36.56s`) — don't silently reuse the plan-time numbers if they've drifted (a corpus/model/network variance check, matching this project's own "get each number from its own dedicated run" rule).

**Step 2 — no commit** (spike only, scratchpad files deleted after).

---

### Chunk 11.1 — `RerankConfig.max_length` field

**Files**: Modify `src/config/settings.py`, `tests/config/test_settings.py`, `config.yaml`, `config.example.yaml`.

**Step 1 — write failing test**:
```python
def test_rerank_max_length_defaults_to_none(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("chunking:\n  min_tokens: 400\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    settings = Settings()

    assert settings.rerank.max_length is None


def test_rerank_max_length_loads_from_yaml(tmp_path, monkeypatch):
    yaml_content = "rerank:\n  max_length: 256\n"
    (tmp_path / "config.yaml").write_text(yaml_content)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    settings = Settings()

    assert settings.rerank.max_length == 256
```

**Step 2 — verify failure**: `pydantic.ValidationError`/`AttributeError` — `RerankConfig` has no `max_length` field yet.

**Step 3 — implement minimal code** (`src/config/settings.py`):
```python
class RerankConfig(BaseModel):
    enabled: bool = True
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k: int = 5
    max_length: int | None = None
```
Add `rerank.max_length: <candidate value, decided in Chunk 11.3>` to both `config.yaml` and `config.example.yaml` once the real value is chosen — for now, leave both files' `rerank:` sections unchanged (field defaults to `None`, current behavior preserved) until Chunk 11.3 picks a real number.

**Step 4 — verify pass**: `uv run pytest tests/config/test_settings.py -v` → new tests green, no existing test broken.

**Step 5 — commit**: `git add src/config/settings.py tests/config/test_settings.py && git commit -m "[Feature] Config: add rerank.max_length field (default None, no behavior change yet)"`

---

### Chunk 11.2 — thread `max_length` into `_get_model`/`CrossEncoder`

**Files**: Modify `src/rerank/cross_encoder.py`, `tests/rerank/test_cross_encoder.py`.

**Step 1 — write failing test**:
```python
def test_rerank_passes_max_length_to_get_model(monkeypatch):
    captured = {}

    class FakeModel:
        def predict(self, pairs):
            return [0.0] * len(pairs)

    def fake_get_model(name, max_length):
        captured["max_length"] = max_length
        return FakeModel()

    monkeypatch.setattr(cross_encoder, "_get_model", fake_get_model)
    config = RerankConfig(enabled=True, max_length=256, top_k=1)

    rerank("q", [("a", "text")], config)

    assert captured["max_length"] == 256
```
Also update all five existing fakes (listed in the Conventions Check above) to accept the new parameter: `lambda name, max_length: ...` (or `pytest.fail(...)` bodies unchanged, just the signature).

**Step 2 — verify failure**: `TypeError: fake_get_model() takes 1 positional argument but 2 were given` on the real call site once Step 3 below is written first for the *other* direction — actually: write this test first, confirm it fails because `_get_model`/`rerank()` don't pass `max_length` yet (`TypeError: <lambda>() takes 1 positional argument but 2 were given` is backwards — the RED state here is the *new* test failing because `rerank()` doesn't yet call `_get_model(config.model, config.max_length)`, so `fake_get_model(name, max_length)` never receives its second arg and the assertion on `captured["max_length"]` fails with a `KeyError`). Confirm this exact failure before implementing.

**Step 3 — implement minimal code** (`src/rerank/cross_encoder.py`):
```python
_models: dict[tuple[str, int | None], CrossEncoder] = {}


def _get_model(model_name: str, max_length: int | None) -> CrossEncoder:
    key = (model_name, max_length)
    if key not in _models:
        _models[key] = CrossEncoder(model_name, device="cpu", max_length=max_length)
    return _models[key]
```
Update `rerank()`'s call site: `model = _get_model(config.model, config.max_length)`. Update the five existing fakes' signatures per the Conventions Check list.

**Step 4 — verify pass**: `uv run pytest tests/rerank/test_cross_encoder.py -v` → all 8 tests (7 existing + 1 new) green.

**Step 5 — commit**: `git add src/rerank/cross_encoder.py tests/rerank/test_cross_encoder.py && git commit -m "[Feature] Rerank: thread max_length into CrossEncoder, re-key model cache by (name, max_length)"`

---

### Chunk 11.3 — real tuning run: pick `top_n`/`max_length`, verify against the eval harness

**Files**: Modify `config.yaml`, `config.example.yaml` (temporarily, then to final chosen values).

**Step 1 — cheap iteration via `--retrieval-only`** (zero API cost, per Block 9's established pattern): starting hypothesis `retrieval.top_n: 20 → 10`, `rerank.max_length: <unset> → 256`. Run `PYTHONPATH=src uv run python -m app.main eval --index data/index --retrieval-only` after each change; compare `mean_recall_at_k`/`mean_mrr`/`mean_ndcg` against the real committed baseline (`0.616/0.906/0.783`) and `eval.tolerance` (0.1). If either value pushes a metric outside tolerance, back off (e.g. `top_n=15`, or drop `max_length` entirely) — real evidence decides the final numbers, not the starting hypothesis.

**Step 2 — real timed query** at the candidate config: re-run Chunk 11.0's timing probe, confirm an actual measured latency drop (report the real number, whatever it is).

**Step 3 — one real full `eval` run** (judge-scored, real cost) at the final candidate config to confirm `correctness_rate`/`completeness_rate` aren't regressed beyond `eval.tolerance` vs. the current baseline (`0.875/0.625`) — generation-level metrics could move if reranking now surfaces different/fewer chunks, which `--retrieval-only` mode can't detect on its own.

**Step 4 — commit the final chosen values** to both `config.yaml` and `config.example.yaml` (kept in sync, per the Block 4 audit's config-template-drift lesson).

**Step 5 — commit**: `git add config.yaml config.example.yaml && git commit -m "[Perf] Retrieval/Rerank: tune top_n/max_length for latency, verified against real eval baseline"` — commit message states the actual real before/after numbers found in Steps 1-3, not the hypothesis.

---

### Chunk 11.4 — `prompts/answer_v2.md` + `PROMPT_VERSION` bump

**Files**: Create `prompts/answer_v2.md`. Modify `src/generate/prompt.py`, `tests/generate/test_prompt.py`.

**Step 1 — write failing test**:
```python
def test_prompt_version_is_answer_v2():
    assert PROMPT_VERSION == "answer_v2"


def test_build_prompt_does_not_instruct_inline_bracket_citation():
    prompt = build_prompt("any question", [("id1", "some text")])

    assert "square brackets" not in prompt.lower()


def test_build_prompt_still_instructs_the_citations_field_contract():
    prompt = build_prompt("any question", [("id1", "some text")])

    assert "citations" in prompt.lower()
    assert "only" in prompt.lower()  # "supports a claim... only if"
```
(Existing `test_build_prompt_instructs_context_only_and_citation_by_id`'s `"cite" in prompt.lower()` assertion is revisited in Step 3 — the new prompt still discusses citing, via the `citations` field, so the word should still appear naturally; confirm rather than assume.)

**Step 2 — verify failure**: `PROMPT_VERSION == "answer_v1"` still, `_TEMPLATE_PATH` points at `answer_v1.md` which still contains "square brackets" — both new tests fail for the right reason.

**Step 3 — implement minimal code**: create `prompts/answer_v2.md`:
```
You are answering questions about the FAA Airplane Flying Handbook using only the excerpts provided below. Write a clear, well-organized answer in plain prose — do not include the excerpts' bracketed chunk ids anywhere in your answer text. If the excerpts do not contain enough information to answer, say so honestly instead of guessing — do not use outside knowledge.

Separately from the answer text, populate the `citations` field with only the chunk ids (shown in brackets before each excerpt below) whose content directly supports a claim in `answer_text`. This is the only place citations belong — not inline in the prose. If none of the excerpts answer the question, `citations` must be an empty list — even if you mention what an excerpt covers instead, mentioning it is not citing it.

Question: {question}

Excerpts:
{context}
```
Update `src/generate/prompt.py`: `PROMPT_VERSION = "answer_v2"`.

**Step 4 — verify pass**: `uv run pytest tests/generate/test_prompt.py -v` → all tests green (update the existing `"cite" in prompt.lower()` assertion's exact wording only if the new draft doesn't naturally contain "cite" — check first, don't pre-emptively weaken the assertion).

**Step 5 — commit**: `git add prompts/answer_v2.md src/generate/prompt.py tests/generate/test_prompt.py && git commit -m "[Feature] Generation: answer_v2 drops inline bracket-citation instruction, keeps citations field contract"`

---

### Chunk 11.5 — live-API verification: no inline brackets, citations still populated

**Files**: Modify `tests/generate/test_client.py` (or a new `tests/generate/test_answer_v2_live.py`, matching whichever file already hosts `generate_answer`'s existing live-API tests — check first).

**Step 1 — write failing test** (gated `@pytest.mark.slow @pytest.mark.live_api`, `RUN_LIVE_API_TESTS=1`):
```python
import re

@pytest.mark.slow
@pytest.mark.live_api
def test_generate_answer_v2_produces_no_inline_bracket_citations(real_client):
    chunks = [("stall001", "Stalls occur when the critical angle of attack is exceeded.")]

    answer = generate_answer(real_client, "What causes a stall?", chunks, GenerationConfig())

    assert not re.search(r"\[[0-9a-f]{8,}\]", answer.answer_text)
    assert "stall001" in answer.citations
```
(Reuse whatever real-client fixture the existing live-API tests in this file already use — check `tests/generate/test_client.py`'s existing live tests first rather than inventing a new fixture.)

**Step 2 — verify failure**: skipped by default (no `RUN_LIVE_API_TESTS=1`) — run explicitly with the env var set to see the real result against `answer_v2`. If the model still emits brackets on this first real attempt, that is itself real information, not a test-writing mistake — proceed to Chunk 11.6 rather than assume the first prompt draft holds (per Block 4's own precedent: its citation rule needed a second real fix before holding in general).

**Step 3 — implement**: only if Step 2 shows real leakage — revise `prompts/answer_v2.md`'s wording (e.g., strengthen "do not include... anywhere" or add an explicit negative example) and re-run the live test. Do not silently accept a flaky/partial pass.

**Step 4 — verify pass**: `RUN_LIVE_API_TESTS=1 uv run pytest tests/generate/test_client.py -v -m live_api -k answer_v2` → real pass against the real API.

**Step 5 — commit**: `git add tests/generate/test_client.py && git commit -m "[Test] Generation: live-API verification that answer_v2 emits no inline bracket citations"` (include prompt wording changes from Step 3 in the same commit if any were needed).

---

### Chunk 11.6 — real full eval run (both tracks combined), decide keep/revert

**Files**: no code changes — a real operational verification run.

**Step 1**: `PYTHONPATH=src uv run python -m app.main eval --index data/index` (full mode, real judge calls) against the now-changed `config.yaml` (Chunk 11.3's tuned `top_n`/`max_length`) and `answer_v2` (Chunk 11.4). Capture the real `correctness_rate`/`completeness_rate`/`mean_coverage` output.

**Step 2**: compare against the current baseline (`correctness_rate=0.875, completeness_rate=0.625`). If within `eval.tolerance`, both tracks are confirmed safe to keep. If not, identify which track (A or B) is responsible — re-run each independently against baseline if the combined result is ambiguous — and revert or further tune only the responsible track, not both blindly.

**Step 3**: if confirmed safe, save the new state as the tracked baseline: `--save-baseline` (this becomes the new reference for `cheap-gate.yml`/`nightly-eval.yml` going forward).

**Step 4 — no code change** (this chunk is a real verification gate, not an implementation step).

**Step 5 — no separate commit** (the baseline JSON file itself is the artifact — `git add eval/baselines/<new>.json && git commit -m "[Chore] Eval: save baseline after Block 11 latency/citation-noise tuning"`).

---

### Chunk 11.7 — docs: `BUGS.md`, `.agent/decisions.log`, README

**Files**: Modify `BUGS.md`, `.agent/decisions.log`, `README.md`.

**Step 1**: `BUGS.md` — check off the README's existing inline-bracket-citation callout (in the Chat Interface section) as resolved, referencing `answer_v2`; log the new `generation.timeout_seconds=30.0` reliability finding from Chunk 11.0's probe as a new, real, not-yet-fixed item (per Decision 6).

**Step 2**: `.agent/decisions.log` — append this block's decisions (1-6 above) in the established format.

**Step 3**: `README.md` — update the Chat Interface section's "two things worth calling out" list: remove or rewrite the inline-bracket-citation caveat (no longer true after `answer_v2`), and mention the real measured latency improvement with real before/after numbers (per this project's "every command/claim is verified against reality" convention — pull the actual Chunk 11.0/11.3 numbers, don't restate the plan's hypothesis as if it were the final result).

**Step 4 — verify**: re-read the updated README section for accuracy against the real numbers captured in Chunks 11.0/11.3/11.6.

**Step 5 — commit**: `git add BUGS.md .agent/decisions.log README.md && git commit -m "[Docs] Block 11 closeout: latency/citation-noise fixes, real before/after numbers"`

---

## Technical Debt Strategy

- `generation.timeout_seconds=30.0` stays uncomfortably tight relative to real observed generation latency (Decision 6) — logged to `BUGS.md`, not fixed here. If Track A's real latency reduction doesn't bring generation calls comfortably under 30s on their own, revisit raising this value as a *separate*, reliability-motivated change (not a latency fix).
- `_get_model`'s cache re-keying (Decision 2) is a correctness improvement with no live bug behind it today — noted as intentional, not deferred debt.
- If Chunk 11.5's live-API test reveals `answer_v2`'s first draft doesn't fully suppress inline brackets, the iteration in Chunk 11.5 Step 3 is expected, tracked work — not technical debt, since the plan explicitly anticipates it (Predicted-Behavior Claim Check).

## Production & Design Standards (P0)

- **Timeout Mapping**: no new external calls introduced; existing `GenerationConfig.timeout_seconds`/`CitationConfig.timeout_seconds` (30.0 each) already bound every real API call this block touches. The one real timeout gap found (Decision 6) is logged, not silently left unmentioned.
- **Error Handling**: unchanged — Chunk 10.7's `st.error` boundary in `streamlit_app.py` already covers a real `APITimeoutError` surfacing from this pipeline.
- **Loading States**: unchanged — Chunk 10.5's `st.spinner` already covers this block's (hopefully shorter) wait.

## For UI Features

N/A — no UI code changes in this block (only config, prompt, and eval-harness usage).

---

Ready to start building? Use `/build`.
