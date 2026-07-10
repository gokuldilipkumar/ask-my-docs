# Project History

**Project Goal:** Build a production-shaped, domain-specific RAG system ("Ask My Docs") over the FAA Airplane Flying Handbook (FAA-H-8083-3C) — hybrid retrieval (BM25 + dense) fused via RRF, cross-encoder reranking, grounded generation with verified citations via the Anthropic API, an evaluation harness with a CI quality gate, and full tracing/observability via Langfuse. The pipeline is ~20% of the work; proving it works (and catching regressions) is the point. Full spec: `production-rag-build-prompt.md`.

**Target Audience:** Portfolio piece for hiring managers / potential clients — demonstrates production RAG engineering (hybrid retrieval, reranking, citation verification, eval-gated CI, observability), not just a working demo. README, eval report, and architecture diagram should be presentation-quality and explain the reasoning behind architecture choices, not just what was built.

---

## Core Philosophy

### The Problem This Solves

Most RAG demos stop at "it retrieves and generates an answer." That's not production-shaped — there's no way to know if it's *right*, no way to catch regressions when a prompt or chunking strategy changes, and no visibility into cost/latency/failure rate in production.

**Before this project:**
- No verifiable way to trust a RAG answer's citations
- No regression detection when retrieval/prompt/config changes
- No observability into per-request cost, latency, or failure modes

**After this project:**
- Every citation is verified against its source chunk, not just formatted
- CI fails automatically if a change regresses retrieval quality
- Every query produces a traced, cost/latency/coverage-instrumented request

---

## Key Design Decisions

Full one-line log in `.agent/decisions.log`; full reasoning/explanations in `LEARNING_NOTES.md`. Highlights: `sentence-transformers` over `fastembed` (CPU speed claims didn't hold up in research), `lancedb` for the vector store, `pymupdf` (not plain text extraction) for ingestion since subsection headings need font metadata to detect reliably, content-hash chunk IDs (not row-index) so re-ingestion doesn't break citations.

---

## Session Log

| Date | What I Did | Key Decisions | Next Steps |
|------|-----------|---------------|------------|
| 2026-07-10 | Read seed spec (`production-rag-build-prompt.md`), proposed initial repo structure/library stack, set up SDLC scaffolding (`.agent/workflows/`, `skills/`, `CLAUDE.md`, `PROJECT_HISTORY.md`) | Audience confirmed as portfolio/hiring-manager facing | Resume `/brainstorm`: library build-vs-borrow research, PRD sections (Architecture, Components, Data Flow, Error Handling), then inspect the actual PDF to propose chunking strategy + sample eval questions |
| 2026-07-10 | Completed `/brainstorm`: library build-vs-borrow research, full PRD (Architecture/Components/Data Flow/Error Handling), inspected the actual PDF (406 pages, 18 chapters, single-column, dual page-numbering, 279 figure captions, zero table captions) to ground the chunking strategy and 8 sample eval questions in real structure. Wrote PRD to `docs/plans/2026-07-10-ask-my-docs-design.md`, decisions to `.agent/decisions.log`, reasoning to `LEARNING_NOTES.md` | Chunking uses pymupdf font metadata (not regex) for subsection detection; content-hash chunk IDs; local eval-response cache + daily cost total added for cost control | Run `/plan` to break the PRD into TDD-ready, bite-sized implementation tasks |
| 2026-07-10 | Session wrap-up: added `.gitignore` (excludes the 273MB PDF and local settings), `git init`, initial commit of all scaffolding + design docs (33 files) | Repo now version-controlled locally; no remote configured yet | **Resume here next session: run `/plan`** against `docs/plans/2026-07-10-ask-my-docs-design.md` to produce the TDD implementation plan |
