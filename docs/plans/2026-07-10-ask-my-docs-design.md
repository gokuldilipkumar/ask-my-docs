# Ask My Docs — Design (PRD)

**Date**: 2026-07-10
**Status**: Approved — ready for `/plan`

## Goal

Build a production-shaped, domain-specific RAG system over the FAA Airplane Flying Handbook (FAA-H-8083-3C): hybrid retrieval (BM25 + dense, fused via RRF), cross-encoder reranking, grounded generation with **verified** citations, an evaluation harness with a CI quality gate, and full tracing/observability. The pipeline itself is ~20% of the work — the eval harness, CI gate, citation verification, and observability are the graded 80% and must not be treated as optional layers.

Full original spec: `production-rag-build-prompt.md`.

## Audience

Portfolio piece for hiring managers / potential clients. Deliverables (README, architecture diagram, eval report) should be presentation-quality and explain *why* each architecture choice was made, not just document what was built.

## Scope — What We're NOT Building

- No local LLM inference (generation/judging via Anthropic API only).
- No GPU dependency — every local model (embeddings, reranker) must run on CPU.
- No multi-tenant auth.
- No large web frontend — CLI is the primary interface, optional minimal UI (streamlit/fastapi) is a stretch goal.
- No fine-tuning.

## Core Requirements

### Repo structure
```
ask-my-docs/
├── src/
│   ├── ingest/          # PDF load, chunk, stable IDs, chapter/section metadata
│   ├── retrieval/       # bm25.py, vector.py, fusion.py (RRF)
│   ├── rerank/          # cross-encoder
│   ├── generate/        # Claude call, grounded-answer prompt
│   ├── citations/       # formatting + faithfulness verification
│   ├── eval/            # golden dataset, retrieval metrics, LLM judges
│   ├── observability/   # tracer interface (Langfuse impl), cost/latency, daily cost total
│   ├── config/          # pydantic settings, yaml loader
│   └── app/             # typer CLI (ingest, query, eval, serve)
├── data/                 # PDF, chunked/indexed artifacts (gitignored)
├── eval/golden/           # golden Q&A dataset (auto vs reviewed flag)
├── prompts/               # versioned prompt templates
├── .github/workflows/     # cheap-gate.yml (on push), nightly-eval.yml
├── tests/
├── config.example.yaml
├── .env.example
└── requirements.txt
```

### Library choices (Build vs. Borrow — all "borrow")

| Component | Library | Why |
|---|---|---|
| PDF parsing | `pymupdf` | Layout-aware block + font-metadata extraction (needed for heading detection — see Chunking Strategy). |
| Sparse retrieval | `bm25s` | Pure numpy/numba, no JVM, ElasticSearch-comparable speed. |
| Dense embeddings | `sentence-transformers` (`bge-small-en-v1.5`) | Chosen over `fastembed` after research showed inconsistent CPU speed claims for `fastembed`; benchmark both on the actual dev machine before locking in. |
| Vector store | `lancedb` | Embedded, scales past RAM via disk-based indexing, built-in hybrid search + reranking support. |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` (default), `bge-reranker-base` (config-swappable) | Both ~130ms/16-candidate batch on CPU; MiniLM-L6-v2 is the standard speed/quality default. |
| Generation + judges | `anthropic` SDK | `claude-sonnet` for answers, `claude-haiku` for eval judges. |
| Tracing | `langfuse` | Cloud free tier first (simpler than Docker on one dev machine); self-host later via the same tracer interface. |
| Schema/config | `pydantic` + `pydantic-settings` | Config-driven, no magic numbers. |
| CLI | `typer` | |
| Tests | `pytest` | |

### Architecture

Modular pipeline, each stage independently swappable via config (this is what makes "disabling reranking visibly changes retrieval" achievable as an acceptance criterion, not just a claim).

**Query-time flow** (every arrow is a traced Langfuse span):
```
question ─┬─→ retrieval.bm25.search() ──┐
          └─→ retrieval.vector.search() ─┴─→ fusion.rrf() → top-N
                                                            → rerank.score() → top-k
                                                            → generate.answer() → {text, citations}
                                                            → citations.verify() → {answer, citations, coverage}
```

**Offline flows**: `ingest` (PDF → chunks → indexes, run once/on re-chunk) and `eval` (golden dataset → metrics; cheap metrics every push, expensive LLM-judge metrics nightly/manual only).

### Components
- `ingest`: PyMuPDF loader (layout + font metadata) → chunker (subsection-boundary-first, sliding-window fallback) → deterministic chunk ID generator → writes to BM25 index + LanceDB.
- `retrieval`: `bm25.py`, `vector.py`, `fusion.py` (RRF, configurable weights).
- `rerank`: cross-encoder wrapper, model swappable via config.
- `generate`: versioned prompt templates (`prompts/`), Claude API call, structured `{answer_text, citations: [chunk_id]}` output.
- `citations`: formatting + faithfulness verification (LLM-judge/NLI per claim), coverage scoring.
- `eval`: golden dataset schema (pydantic, `auto_generated`/`reviewed` flags), retrieval metrics (Recall@k, MRR, nDCG — pure CPU), answer-quality judges (Haiku, temp 0), **local response cache** keyed on `(question, config_hash)` to avoid re-spending during eval-harness debugging.
- `observability`: `Tracer` protocol + `LangfuseTracer` impl, cost calculator (token usage × price table), **daily running cost total** (not just per-request) surfaced as a budget-runaway signal.
- `config`: pydantic-settings, `config.yaml` + `.env`.
- `app`: typer CLI.

### Chunking strategy (from actual PDF inspection — 406 pages, 18 chapters + Glossary + Index)
- Body text is single-column throughout sampled sections — no 2-column reflow to handle.
- Chapter headers reliably match `^Chapter N: Title$` as plain text (confirmed via extraction).
- Subsection headers are NOT reliably distinguishable via regex alone — use PyMuPDF font-size/bold metadata for heading detection, not text pattern matching.
- Dual page numbering: front matter is roman numerals, body is chapter-relative (`4-1` = Ch. 4 p. 1) — store both PDF page index (navigation) and printed label (citation display, matching the "Ch. 4: Energy Management, p. 4-1" citation format requirement).
- Split on detected subsection boundaries first; fall back to ~400–600 token sliding window with ~15% overlap for long subsections (some span 8+ pages).
- 279 `Figure N-N. <caption>` instances are extractable as plain text inline — attach as a `figure_refs` metadata field on the containing chunk (images themselves aren't retrievable, but captions are a retrieval hook).
- **Zero** `Table N-N.` caption matches found anywhere — tables have no consistent caption convention or are image-rendered. Real risk: spot-check table-heavy pages (weight-and-balance, V-speed reference tables) manually before trusting the chunker on them; do not assume clean extraction.
- CMap encoding warnings appear on nearly every page in `pdftotext`, but a full-text scan found zero garbled/replacement characters — extraction looks clean in practice; spot-check against source pages during implementation regardless.
- Chunk ID = deterministic hash of `(chapter, section_title, sequence)` — stable across re-ingestion independent of raw page/byte offsets.

### Sample eval questions (confirmed against real, adjacent section titles)
1. "What's the difference between VMC and VSO?" (Ch. 13 — adjacent confusable V-speed sections)
2. "What is a secondary stall and how does it differ from an accelerated stall?" (Ch. 5 — adjacent confusable stall types)
3. "How does a short-field takeoff differ from a soft-field takeoff?" (Ch. 6 — adjacent confusable procedures)
4. "What are the common errors during a crosswind takeoff?" (baseline precision check)
5. "Explain the three basic rules of energy control." (Ch. 4 — tests specific-subsection surfacing over generic chapter content)
6. "What should a pilot do during upset prevention and recovery training?" (broad phrasing, tests correct scoping)
7. "What is the FAA Wings Program?" (narrow lookup, tests against over-retrieval)
8. "Does this handbook cover helicopter autorotation procedures?" (deliberately out-of-scope — tests the "honest I don't have that" criterion)

## Success Criteria (Acceptance Criteria)
- Ask a question over the corpus → get an answer with **verified** citations resolvable to source + location; insufficient context yields an honest "I don't have that," not a hallucination.
- Disabling reranking or switching fusion weights via config visibly changes retrieval.
- Eval harness prints retrieval + answer metrics vs. baseline.
- A deliberately bad prompt/config change fails the CI gate; a good one passes.
- Every query produces a Langfuse trace with per-stage spans; dashboard shows p50/p95 latency, cost/request, citation coverage, failure rate.
- Each trace and eval run is attributable to a specific prompt version.

## Edge Cases & Failure Modes
- **Empty/weak retrieval**: `generate` returns an honest "I don't have that" instead of forcing weak chunks into the prompt.
- **Unsupported citation**: `citations.verify` strips it and downgrades `coverage`; response flagged `low_confidence` below a config threshold (not blocked).
- **Malformed/image-only PDF content**: skipped or tagged `content_type: figure`, never turned into a garbled-text chunk.
- **Anthropic API errors**: bounded retry (3 attempts, backoff); final failure returns a structured error and increments the `failure_rate` metric.
- **Non-deterministic judge scores**: temp 0 reduces but does not eliminate variance (floating-point non-associativity in batched inference, non-guaranteed backend reproducibility) — CI gate uses tolerance bands, not hard cutoffs.
- **Re-ingestion drift**: chunk IDs are content-hash-based, not row-index-based, so re-ingestion after a wording tweak doesn't invalidate golden eval references.
- **Cost runaway**: cheap retrieval gate (zero API cost) on every push; expensive answer-eval nightly/manual only; bounded retries; local response cache for eval-harness debugging; daily running cost total surfaced from Langfuse, not just per-request cost.

## Related
- `LEARNING_NOTES.md` — full reasoning/explanations behind these decisions, concept deep-dives (hybrid retrieval, reranking, citation verification, temp-0 determinism, cost runaway).
- `.agent/decisions.log` — one-line decision log.
