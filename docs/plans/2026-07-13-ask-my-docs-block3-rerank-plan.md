# Block 3 Implementation Plan — Cross-Encoder Reranking

**Date**: 2026-07-13
**Parent plan**: `2026-07-11-ask-my-docs-implementation-plan.md` (Block 3 sketch, line ~1528)
**Design doc**: `2026-07-10-ask-my-docs-design.md`

## Header

- **Goal**: Rerank hybrid retrieval's fused top-N candidates down to top-k using a config-swappable cross-encoder, with `enabled=False` as a true no-op passthrough.
- **Architecture**: One new module (`src/rerank/cross_encoder.py`) exposing a single `rerank()` function, plus one ingest-side helper (`get_chunk_texts` on the existing LanceDB table) so the reranker can score `(query, chunk_text)` pairs — `hybrid_retrieve` returns only IDs. No orchestrator: composing retrieve→rerank→generate is Block 4's job (same reuse-audit reasoning that kept Block 2 thin).
- **Design patterns**: Module-level model cache keyed by model name (same pattern as `vector_index._get_model`, extended to a dict because the model is config-swappable). Candidates passed as `(chunk_id, text)` *pairs*, not parallel lists — the Block 2 audit's silent-truncation bug class is prevented structurally, not just by a `strict=True` guard.
- **Tech stack**: `sentence_transformers.CrossEncoder` (`cross-encoder/ms-marco-MiniLM-L-6-v2` default, per design doc), LanceDB (existing table), CPU-only.

## Conventions Check (per `/plan` workflow)

- **Reuse audit**: `hybrid_retrieve` returns `list[str]` of chunk IDs (`src/retrieval/hybrid.py:9-21`). Chunk text lives in the LanceDB `chunks` table (`vector_index.py:23-30` stores `chunk_id`, `text`, `vector`). **No existing fetch-by-id function found** anywhere in `src/` — Chunk 3.1 builds it on the existing table rather than adding any new storage. `bm25s` does not store raw text (only tokenized), so LanceDB is the single source of truth for chunk text. `RerankConfig` already exists (`settings.py:29-32`: `enabled=True`, `model`, `top_k=5`) and `config.yaml` already carries a `rerank:` section — **no config changes needed**.
- **Test style**: pytest, `@pytest.mark.slow` for anything loading a real model, `make_chunk` conftest fixture, probe-verified fixtures for model-dependent assertions (Block 2 lesson), one contract case per chunk (build.md step 3).
- **Config-isolation check**: no new config keys at all, so no corpus-specific values can leak into tests. `RerankConfig` is constructed directly in tests (same convention as `RetrievalConfig` in `test_hybrid.py`).
- **Third-party APIs to verify with a throwaway script before RED** (build.md step 2):
  1. LanceDB filter-without-vector-search: does `table.search().where("chunk_id IN (...)").to_list()` work without a query vector, or does this need `table.query()` / a full `to_pandas()` scan? (617 rows — even a full scan is acceptable; verify which API shape is real.)
  2. `CrossEncoder(model, device="cpu")` + `.predict(list[tuple[str, str]])`: confirm input shape, output (expect `np.ndarray` of unbounded logit scores, higher = more relevant — fine for argsort), and first-use model download (~90 MB) works in this environment.
- **Probe-verified fixture requirement**: Chunk 3.4's discrimination fixture MUST be probed against the real cross-encoder before the test is finalized (record the score margin in a test comment, as `test_hybrid.py:31-35` does). If the planned fixture doesn't discriminate, replace it at RED time — plan fixtures for model behavior are hypotheses (Block 2, Chunk 2.2 precedent).

## Block 3: Cross-Encoder Reranking

**Success criteria**
- [ ] `rerank()` reorders a fused candidate list and truncates to `config.top_k` (real-model test + real-corpus spot-check).
- [ ] Model is swappable via `settings.rerank.model` with zero code changes (verified by a fake-model test asserting the configured name is what gets loaded).
- [ ] `enabled=False` is a no-op passthrough: preserves fused order, truncates to `top_k`, and **never loads the model** (asserted via monkeypatch).
- [ ] Contract cases covered: empty candidate list; `top_k` larger than the candidate count.
- [ ] Real-corpus spot-check: toggling `rerank.enabled` visibly changes the top-5 for at least one of the three sample queries (design-doc acceptance criterion), with per-query rerank latency measured on this CPU (design claim: ~130 ms / 16-candidate batch).

---

### Chunk 3.1 — `get_chunk_texts` on the LanceDB table

**Files**: Modify `src/ingest/vector_index.py`; Modify `tests/ingest/test_vector_index.py`.

**Step 1 — failing tests** (append to `tests/ingest/test_vector_index.py`; adapt imports to the file's existing style):

```python
@pytest.mark.slow
def test_get_chunk_texts_returns_texts_keyed_by_id(tmp_path, make_chunk):
    chunks = [
        make_chunk("a", "Text about aerodynamic stalls."),
        make_chunk("b", "Text about crosswind landings."),
    ]
    build_vector_index(chunks, tmp_path / "lancedb")

    texts = get_chunk_texts(tmp_path / "lancedb", ["b", "a"])

    assert texts == {
        "a": "Text about aerodynamic stalls.",
        "b": "Text about crosswind landings.",
    }


@pytest.mark.slow
def test_get_chunk_texts_raises_on_unknown_id(tmp_path, make_chunk):
    build_vector_index([make_chunk("a", "Some text.")], tmp_path / "lancedb")

    with pytest.raises(KeyError):
        get_chunk_texts(tmp_path / "lancedb", ["a", "missing-id"])
```

The KeyError contract is deliberate (fail loud): a missing ID means the caller's IDs and the index are out of sync — silently returning fewer texts than requested is the same silent-degradation class as the RRF zip bug.

**Step 2 — verify failure**: `uv run pytest tests/ingest/test_vector_index.py -q` → `ImportError: cannot import name 'get_chunk_texts'`.

**Step 3 — minimal implementation** (append to `src/ingest/vector_index.py`; exact filter API subject to the throwaway-script verification above):

```python
def get_chunk_texts(db_path: Path, chunk_ids: list[str]) -> dict[str, str]:
    db = lancedb.connect(str(db_path))
    table = db.open_table("chunks")
    # chunk_ids are content hashes (hex), so embedding them in the filter string is safe
    id_list = ", ".join(f"'{cid}'" for cid in chunk_ids)
    rows = table.search().where(f"chunk_id IN ({id_list})").to_list()
    texts = {r["chunk_id"]: r["text"] for r in rows}
    missing = [cid for cid in chunk_ids if cid not in texts]
    if missing:
        raise KeyError(f"chunk_ids not found in index: {missing}")
    return texts
```

**Step 4 — verify pass**: `uv run pytest tests/ingest/test_vector_index.py -q` → all green.

**Step 5 — commit**: `git add src/ingest/vector_index.py tests/ingest/test_vector_index.py && git commit -m "[Feature] Ingest: fetch chunk texts by id from the LanceDB table"`

---

### Chunk 3.2 — `rerank()` module: disabled passthrough + empty-candidates contract

**Files**: Create `src/rerank/cross_encoder.py`; Create `tests/rerank/__init__.py` (if the test tree needs it — mirror existing test dirs), `tests/rerank/test_cross_encoder.py`.

**Step 1 — failing tests** (both fast — no model anywhere near them):

```python
import pytest

from config.settings import RerankConfig
from rerank import cross_encoder
from rerank.cross_encoder import rerank


def test_disabled_rerank_preserves_fused_order_and_truncates(monkeypatch):
    monkeypatch.setattr(
        cross_encoder, "_get_model",
        lambda name: pytest.fail("passthrough must not load the model"),
    )
    candidates = [("b", "text b"), ("a", "text a"), ("c", "text c")]
    config = RerankConfig(enabled=False, top_k=2)

    assert rerank("any query", candidates, config) == ["b", "a"]


def test_empty_candidates_return_empty_without_loading_model(monkeypatch):
    monkeypatch.setattr(
        cross_encoder, "_get_model",
        lambda name: pytest.fail("empty input must not load the model"),
    )
    config = RerankConfig(enabled=True, top_k=5)

    assert rerank("any query", [], config) == []
```

**Step 2 — verify failure**: `uv run pytest tests/rerank -q` → `ModuleNotFoundError: No module named 'rerank.cross_encoder'`.

**Step 3 — minimal implementation**:

```python
from sentence_transformers import CrossEncoder

from config.settings import RerankConfig

_models: dict[str, CrossEncoder] = {}


def _get_model(model_name: str) -> CrossEncoder:
    if model_name not in _models:
        _models[model_name] = CrossEncoder(model_name, device="cpu")
    return _models[model_name]


def rerank(query: str, candidates: list[tuple[str, str]], config: RerankConfig) -> list[str]:
    ids = [cid for cid, _ in candidates]
    if not config.enabled or not candidates:
        return ids[: config.top_k]
    raise NotImplementedError  # scoring path lands in Chunk 3.3/3.4
```

(If `NotImplementedError` in a committed chunk feels wrong at build time, defer the `raise` line and let Chunk 3.3's RED test drive the scoring path into existence — either is acceptable; do not implement scoring before a test demands it.)

**Step 4 — verify pass**: `uv run pytest tests/rerank -q` → 2 passed.

**Step 5 — commit**: `git add src/rerank/cross_encoder.py tests/rerank/ && git commit -m "[Feature] Rerank: disabled/empty passthrough returns fused order without model load"`

---

### Chunk 3.3 — configured model name is what gets loaded

**Files**: Modify `src/rerank/cross_encoder.py`; Modify `tests/rerank/test_cross_encoder.py`.

**Step 1 — failing test** (fast — fake model):

```python
def test_rerank_loads_the_model_named_in_config(monkeypatch):
    captured = {}

    class FakeModel:
        def predict(self, pairs):
            return [0.0] * len(pairs)

    def fake_get_model(name):
        captured["name"] = name
        return FakeModel()

    monkeypatch.setattr(cross_encoder, "_get_model", fake_get_model)
    config = RerankConfig(enabled=True, model="some/other-reranker", top_k=1)

    rerank("q", [("a", "text")], config)

    assert captured["name"] == "some/other-reranker"
```

**Step 2 — verify failure**: `uv run pytest tests/rerank -q` → `NotImplementedError` (or `AssertionError` if 3.2 omitted the raise).

**Step 3 — minimal implementation** (replace the `raise` with the scoring path):

```python
    model = _get_model(config.model)
    scores = model.predict([(query, text) for _, text in candidates])
    ranked = sorted(
        zip(ids, scores, strict=True), key=lambda pair: pair[1], reverse=True
    )
    return [cid for cid, _ in ranked[: config.top_k]]
```

`strict=True` even though `predict` should return one score per pair — the RRF audit finding, applied by default.

**Step 4 — verify pass**: `uv run pytest tests/rerank -q` → 3 passed.

**Step 5 — commit**: `git add src/rerank/cross_encoder.py tests/rerank/test_cross_encoder.py && git commit -m "[Feature] Rerank: score candidates with the config-named cross-encoder"`

---

### Chunk 3.4 — real cross-encoder reorders and truncates (slow, probe-verified)

**Pre-step (build.md step 2)**: throwaway script — load `cross-encoder/ms-marco-MiniLM-L-6-v2` on CPU, predict on the planned fixture pairs below, print scores. Confirms the API shape AND probe-verifies the fixture margins in one pass. Record the measured margins in the test comment. If the fixture doesn't discriminate (relevant candidate doesn't win by a clear margin), replace the candidate texts and re-probe before writing the test — Block 2's Chunk 2.2 contingency, now standard.

**Files**: Modify `tests/rerank/test_cross_encoder.py`.

**Step 1 — failing tests**:

```python
@pytest.mark.slow
def test_rerank_puts_semantically_relevant_candidate_first():
    # Fixture probe-verified against the real model at build time; margins: <record here>
    # "off" contains the keyword but is semantically off-topic (same fixture design as
    # test_hybrid.py's weight-flip test); a cross-encoder should see through it.
    candidates = [
        ("off", "stall stall stall invoice paperwork filing cabinet office supplies."),
        ("rel", "Exceeding the critical angle of attack makes the wing stop producing lift."),
    ]
    config = RerankConfig(enabled=True, top_k=2)

    result = rerank("What causes an aerodynamic stall?", candidates, config)

    assert result[0] == "rel"


@pytest.mark.slow
def test_rerank_truncates_to_top_k_and_handles_top_k_beyond_len():
    candidates = [
        ("a", "Exceeding the critical angle of attack makes the wing stop producing lift."),
        ("b", "Weight and balance must be computed before every flight."),
        ("c", "Radio communication procedures at towered airports."),
    ]
    top2 = rerank("What causes an aerodynamic stall?", candidates, RerankConfig(top_k=2))
    all3 = rerank("What causes an aerodynamic stall?", candidates, RerankConfig(top_k=10))

    assert len(top2) == 2
    assert sorted(all3) == ["a", "b", "c"]  # top_k beyond len returns all, no error
```

**Step 2 — verify failure**: these should PASS if 3.3's implementation is complete — expected outcome is **green-on-first-run**. That's acceptable here because the *behavior under test* (real-model discrimination, truncation bounds) wasn't previously covered by any test; watch them run against the real model once. If either fails, the fixture probe or the implementation is wrong — debug before proceeding, don't weaken the assertion.

**Step 3/4 — verify**: `uv run pytest tests/rerank -q` → 5 passed (2 slow). Full suite: `uv run pytest -q` → all green.

**Step 5 — commit**: `git add tests/rerank/test_cross_encoder.py && git commit -m "[Test] Rerank: real cross-encoder discrimination and top-k truncation"`

---

### Chunk 3.5 — real-corpus spot-check + latency measurement (manual, no new tests)

**Files**: none committed (throwaway script in scratchpad); findings go to `BUGS.md` (if any), `PROJECT_HISTORY.md`, `LEARNING_NOTES.md`.

1. For each of the three sample queries (aerodynamic stall, VMC/VSO, crosswind landing): run `hybrid_retrieve` (top_n=20) against the real indexes → `get_chunk_texts` → `rerank` (top_k=5), once with `enabled=True` and once with `enabled=False`.
2. **Acceptance (design doc)**: the enabled/disabled top-5 lists differ visibly for at least one query. Record which chunks moved and whether the reranked order is *subjectively better* (read the chunks — is the #1 actually the best answer?). Reranking that reorders but degrades is a finding, not a pass.
3. **Latency**: time the `rerank` call per query (20 candidates) on this CPU. Design claim: ~130 ms per 16-candidate batch. If it's wildly off (>5x), log to `BUGS.md` — it affects Block 4's serving-path budget.
4. Log all findings; check off the Block 3 success criteria in this file.

---

## Technical Debt Strategy (log to `BUGS.md` at build time if accepted)

- `get_chunk_texts` opens a fresh LanceDB connection per call and filters without any index on `chunk_id` — fine at 617 rows; revisit alongside the existing "hybrid_retrieve reloads BM25 per query" serving-path item in Block 4.
- `rerank` returns bare IDs, discarding the text the caller just fetched; Block 4's generation stage will need id→text again (double fetch). Acceptable now — Block 4's plan should decide whether the pipeline passes `(id, text)` pairs end-to-end instead.
- `_models` cache never evicts (two models resident if config swaps mid-process). Fine for a single-model CLI; note only.
- First `CrossEncoder` use downloads ~90 MB from HuggingFace — CI caching strategy is Block 7's concern (same situation as the existing bge-small embedding model).

## Production Standards (P0)

- No network calls at query time (model download happens once at first load, before serving). No timeouts to map; no new env vars or secrets.
- All failure modes raise (KeyError on missing chunk IDs, ValueError on score-length mismatch via `strict=True`) — no silent degradation paths.
- Tests loading real models are `@pytest.mark.slow`, consistent with the existing suite.
