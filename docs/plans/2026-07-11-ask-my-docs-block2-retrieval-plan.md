# Ask My Docs — Implementation Plan (Block 2: Hybrid Retrieval)

**Date**: 2026-07-11
**Status**: Ready for `/build`
**Source design**: `docs/plans/2026-07-10-ask-my-docs-design.md`
**Follow-on to**: `docs/plans/2026-07-11-ask-my-docs-implementation-plan.md` (Block 0 + Block 1, built and committed this session)

## Scope

Full TDD chunk detail for Block 2 only (hybrid retrieval — BM25 + vector fused via RRF), per the block-by-block `/plan` cadence chosen on 2026-07-11. Blocks 3–9 remain sketched at block-level in the prior plan doc.

## Header

- **Goal**: Given a query, return a single ranked list of `chunk_id`s that fuses BM25 (sparse) and vector (dense) retrieval via config-weighted Reciprocal Rank Fusion (RRF), so that changing fusion weights measurably changes the returned ordering — one of the design doc's stated acceptance criteria.
- **Architecture**: A thin orchestration layer over Block 1's existing index infrastructure. `retrieval/fusion.py` is a new, pure, I/O-free RRF implementation (real new logic — nothing to reuse). `retrieval/hybrid.py` is a new orchestrator that calls Block 1's *existing* `ingest.bm25_index.load_bm25_index`/`search_bm25` and `ingest.vector_index.search_vector` directly, then fuses their rankings. No new search/index code is written — see Reuse Audit below.
- **Design Patterns**: Pure functions throughout (same as Block 1) — `reciprocal_rank_fusion` takes ranked ID lists in, returns a ranked ID list out, no side effects. `hybrid_retrieve` is the one function with I/O (reads persisted indexes from disk).
- **Tech Stack**: No new dependencies — reuses `bm25s`, `lancedb`, `sentence-transformers` already installed, plus `src/config/settings.py`'s `RetrievalConfig` (already exists: `rrf_k`, `bm25_weight`, `vector_weight`, `top_n`).

### Reuse Audit (per `.agent/workflows/plan.md`)

Searched the codebase before planning any new function:

| Need | Existing function | Verdict |
|---|---|---|
| Load a persisted BM25 index and search it | `ingest.bm25_index.load_bm25_index`, `ingest.bm25_index.search_bm25` (`src/ingest/bm25_index.py:22-31`) | **Call directly, don't re-implement.** Already returns a ranked `list[str]` of `chunk_id`s. |
| Search a persisted vector index | `ingest.vector_index.search_vector` (`src/ingest/vector_index.py`) | **Call directly, don't re-implement.** Already takes `(db_path, query, top_k)` and returns a ranked `list[str]`. |
| RRF fusion | — | **No existing equivalent found.** New code, Chunk 2.1. |
| Weighted-config-driven retrieval orchestration | — | **No existing equivalent found.** New code, Chunk 2.2. |

This is why Block 2 has no `retrieval/bm25.py` or `retrieval/vector.py` wrapper files despite the design doc's repo-structure sketch naming them — a wrapper with no new behavior over an existing function is exactly the premature-abstraction case `CLAUDE.md` says to avoid. `retrieval/hybrid.py` calls Block 1's functions directly.

### Conventions (carried over from Block 1, still apply)
- Tests build real (small, synthetic) BM25 + vector indexes in `tmp_path` via `ingest.bm25_index.build_bm25_index` / `ingest.vector_index.build_vector_index` — same `_chunk()` helper pattern already used in `tests/ingest/test_bm25_index.py` and `tests/ingest/test_vector_index.py`. No mocking of `bm25s`/`lancedb`/`sentence-transformers`.
- Anything that loads the real embedding model is marked `@pytest.mark.slow` (established in Block 1).
- pytest, `src/`-layout, `pythonpath = ["src"]` — unchanged from Block 0.

## Block 2: Hybrid Retrieval

### Success Criteria
- [ ] `reciprocal_rank_fusion` combines N ranked lists into one fused ranking using per-list weights and a configurable `k` constant.
- [ ] A document ranked first in every input list ranks first in the fusion.
- [ ] Zero-weighting one input list makes the fusion match the other list's order exactly (proves weights are load-bearing, not decorative).
- [ ] `hybrid_retrieve` wires real BM25 + vector search through fusion and truncates to `settings.retrieval.top_n`.
- [ ] Changing `bm25_weight`/`vector_weight` in `hybrid_retrieve`'s config measurably changes which chunk ranks first — the design doc's "switching fusion weights via config visibly changes retrieval" acceptance criterion, proven end-to-end against real indexes, not just at the pure-fusion level.

### Chunk 2.1 — Reciprocal Rank Fusion (pure function)

**Files**: Create: `src/retrieval/fusion.py`, `tests/retrieval/test_fusion.py`.

**Step 1: Write failing tests**
```python
# tests/retrieval/test_fusion.py
from retrieval.fusion import reciprocal_rank_fusion


def test_document_ranked_first_in_both_lists_ranks_first_in_fusion():
    ranking_a = ["x", "y", "z"]
    ranking_b = ["x", "z", "y"]

    fused = reciprocal_rank_fusion([ranking_a, ranking_b], weights=[1.0, 1.0], k=60)

    assert fused[0] == "x"


def test_document_present_in_only_one_ranking_still_appears():
    ranking_a = ["x", "y"]
    ranking_b = ["z"]

    fused = reciprocal_rank_fusion([ranking_a, ranking_b], weights=[1.0, 1.0], k=60)

    assert set(fused) == {"x", "y", "z"}


def test_zero_weighting_a_ranking_makes_fusion_match_the_other_rankings_order():
    ranking_a = ["x", "y", "z"]
    ranking_b = ["z", "y", "x"]

    fused = reciprocal_rank_fusion([ranking_a, ranking_b], weights=[1.0, 0.0], k=60)

    assert fused == ["x", "y", "z"]


def test_changing_weights_changes_which_document_ranks_first():
    ranking_a = ["x", "y"]
    ranking_b = ["y", "x"]

    favor_a = reciprocal_rank_fusion([ranking_a, ranking_b], weights=[1.0, 0.1], k=60)
    favor_b = reciprocal_rank_fusion([ranking_a, ranking_b], weights=[0.1, 1.0], k=60)

    assert favor_a[0] == "x"
    assert favor_b[0] == "y"
```

**Step 2: Verify failure**
```bash
uv run pytest tests/retrieval/test_fusion.py -v
```
Expected: `ModuleNotFoundError: No module named 'retrieval.fusion'`.

**Step 3: Implement minimal code**
```python
# src/retrieval/fusion.py
def reciprocal_rank_fusion(
    rankings: list[list[str]], weights: list[float], k: int
) -> list[str]:
    scores: dict[str, float] = {}
    for ranking, weight in zip(rankings, weights):
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + rank)
    return sorted(scores, key=lambda doc_id: scores[doc_id], reverse=True)
```

**Step 4: Verify pass**
```bash
uv run pytest tests/retrieval/test_fusion.py -v
```
Expected: 4 passed.

**Step 5: Commit**
```bash
git add src/retrieval/fusion.py tests/retrieval/test_fusion.py
git commit -m "[Feature] Retrieval: add configurable-weight Reciprocal Rank Fusion"
```

### Chunk 2.2 — `hybrid_retrieve` orchestrator

**Files**: Create: `src/retrieval/hybrid.py`, `tests/retrieval/test_hybrid.py`.

**Step 1: Write failing test**
```python
# tests/retrieval/test_hybrid.py
import pytest

from retrieval.hybrid import hybrid_retrieve
from config.settings import RetrievalConfig
from ingest.bm25_index import build_bm25_index
from ingest.vector_index import build_vector_index
from ingest.models import Chunk


def _chunk(chunk_id, text):
    return Chunk(
        chunk_id=chunk_id,
        chapter_number=4,
        chapter_title="Energy Management",
        section_title="Total Energy",
        page_index_start=0,
        page_index_end=0,
        text=text,
        token_count=len(text.split()),
        sequence=0,
    )


@pytest.mark.slow
def test_hybrid_retrieve_fuses_and_truncates_to_top_n(tmp_path):
    chunks = [
        _chunk("a", "The stall occurs when the critical angle of attack is exceeded."),
        _chunk("b", "Weight and balance must be computed before every flight."),
        _chunk("c", "Radio communication procedures at towered airports."),
        _chunk("d", "Crosswind takeoff and landing techniques for the airplane."),
        _chunk("e", "Slow flight and stall speed procedures during training."),
    ]
    bm25_dir = tmp_path / "bm25"
    vector_dir = tmp_path / "lancedb"
    build_bm25_index(chunks, bm25_dir)
    build_vector_index(chunks, vector_dir)

    config = RetrievalConfig(rrf_k=60, bm25_weight=1.0, vector_weight=1.0, top_n=2)
    results = hybrid_retrieve(bm25_dir, vector_dir, "What causes an aerodynamic stall?", config)

    assert len(results) == 2
    assert "a" in results  # the direct stall-content chunk should surface


@pytest.mark.slow
def test_changing_fusion_weights_changes_top_result(tmp_path):
    # "b" is the only chunk with the exact keyword "balance" (favors BM25);
    # "a" is the closest semantic match for a stall question (favors vector).
    chunks = [
        _chunk("a", "Aerodynamic principles governing lift and critical angle effects."),
        _chunk("b", "balance balance balance weight computations for the airplane."),
    ]
    bm25_dir = tmp_path / "bm25"
    vector_dir = tmp_path / "lancedb"
    build_bm25_index(chunks, bm25_dir)
    build_vector_index(chunks, vector_dir)

    favor_bm25 = RetrievalConfig(rrf_k=60, bm25_weight=5.0, vector_weight=0.01, top_n=2)
    favor_vector = RetrievalConfig(rrf_k=60, bm25_weight=0.01, vector_weight=5.0, top_n=2)

    results_bm25 = hybrid_retrieve(bm25_dir, vector_dir, "balance", favor_bm25)
    results_vector = hybrid_retrieve(bm25_dir, vector_dir, "balance", favor_vector)

    assert results_bm25[0] == "b"
```

**Step 2: Verify failure**
```bash
uv run pytest tests/retrieval/test_hybrid.py -v -m slow
```
Expected: `ModuleNotFoundError: No module named 'retrieval.hybrid'`.

**Step 3: Implement minimal code**
```python
# src/retrieval/hybrid.py
from pathlib import Path

from config.settings import RetrievalConfig
from ingest.bm25_index import load_bm25_index, search_bm25
from ingest.vector_index import search_vector
from retrieval.fusion import reciprocal_rank_fusion


def hybrid_retrieve(
    bm25_index_dir: Path, vector_db_path: Path, query: str, config: RetrievalConfig
) -> list[str]:
    bm25_index, corpus_ids = load_bm25_index(bm25_index_dir)
    bm25_ranking = search_bm25(bm25_index, corpus_ids, query, top_k=config.top_n)
    vector_ranking = search_vector(vector_db_path, query, top_k=config.top_n)

    fused = reciprocal_rank_fusion(
        [bm25_ranking, vector_ranking],
        weights=[config.bm25_weight, config.vector_weight],
        k=config.rrf_k,
    )
    return fused[: config.top_n]
```

**Step 4: Verify pass**
```bash
uv run pytest tests/retrieval/test_hybrid.py -v -m slow
```
Expected: 2 passed. (If `test_changing_fusion_weights_changes_top_result`'s second assertion on `results_vector[0] == "a"` is flaky against the real embedding model's actual similarity scores, loosen to asserting the two configs produce *different* top results rather than a specific chunk — the point is weight-sensitivity, not a specific embedding outcome. Adjust the test at RED time if the first real run shows this.)

**Step 5: Commit**
```bash
git add src/retrieval/hybrid.py tests/retrieval/test_hybrid.py
git commit -m "[Feature] Retrieval: wire hybrid_retrieve orchestrator over BM25+vector fused via RRF"
```

### Chunk 2.3 — Manual verification against the real handbook indexes (not a TDD chunk)

Same spirit as Block 1's Chunk 1.14 — a spot-check, not a RED/GREEN cycle.

**Steps**:
1. Using the real indexes already built at `data/index/bm25` and `data/index/lancedb` (from Block 1's Chunk 1.14 run), call `hybrid_retrieve` with 2-3 of the design doc's confirmed sample eval questions (e.g. "What's the difference between VMC and VSO?").
2. Manually inspect: do the top results look topically right? Does changing `bm25_weight`/`vector_weight` visibly reorder results on the real corpus, not just the synthetic test fixtures?
3. Log findings to `.agent/decisions.log` / `BUGS.md` if anything is materially wrong; if it's just "needs tuning," that's expected — real threshold/weight tuning is Block 6's (eval harness) job once there's a metric to tune against, not a guess made here.

## Technical Debt Strategy

- No new shortcuts introduced in Block 2 itself. Inherits Block 1's open items (`BUGS.md`): token-accurate windowing and the front/back-matter filtering question. Neither blocks Block 2 — `hybrid_retrieve` works over whatever chunks exist in the index regardless of their size distribution.
- `hybrid_retrieve` always queries both BM25 and vector search even if a weight is `0.0` (mathematically zeroed out in fusion, not skipped) — simplest correct implementation; revisit only if profiling later shows the wasted query is a real latency cost (design doc's reranking/generation stages are far more expensive, so this is unlikely to matter).

## Production & Design Standards (adapted — no frontend)

- **Timeout Mapping**: N/A — no network calls in Block 2 (BM25/vector search are local/CPU-only). Anthropic API timeouts remain Block 4's concern.
- **Error Handling**: `hybrid_retrieve` lets exceptions propagate (e.g. missing index directory) rather than swallowing them — consistent with Block 1's ingestion error-handling stance for this stage of the project.
- **Live-Service Test Gate**: no paid API calls in Block 2. The vector-search test is `@pytest.mark.slow` (local model), consistent with Block 1.

## Persistence & Next Step

Saved to `docs/plans/2026-07-11-ask-my-docs-block2-retrieval-plan.md`.

**Ready to start building? Use `/build`.**
