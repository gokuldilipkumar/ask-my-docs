# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- `uv`-managed Python 3.11 project scaffolding (`src/`-layout packages: `ingest`, `retrieval`, `rerank`, `generate`, `citations`, `eval`, `observability`, `config`, `app`).
- Config-driven `Settings` (pydantic-settings): `config.yaml` + `.env` layering, required-secret validation, no magic numbers — chunk size, RRF weights, rerank/citation/eval thresholds all config-driven from the start.
- PDF ingestion pipeline (PyMuPDF): text-span extraction with font metadata, chapter-header detection, subsection-header detection (font-size/bold, sole-line-placement), figure-caption extraction, deterministic content-hash chunk IDs, subsection-boundary-first chunking with a token-aware sliding-window fallback (400-600 tokens, 15% overlap) for oversized sections.
- BM25 sparse index (`bm25s`) and vector index (LanceDB + `bge-small-en-v1.5`) build/search, both with build→reload→search round-trip tests.
- `ingest` CLI command (typer) wiring the full pipeline end to end.
- Ingested the real FAA Airplane Flying Handbook (406 pages): 1,008 chunks across both indexes.

### Fixed
- Subsection-header detection was misclassifying inline bold emphasis (e.g. "**Rule #1:** ...") as standalone headers, fragmenting 60% of real-corpus chunks to under 50 tokens against a 400-600 target. Headers now require sole-line placement, not bold/size alone. Re-ingestion: 1,850 → 1,008 chunks, median chunk size 29 → 173.5 tokens.
- `apply_sliding_window` accepted a `min_tokens` floor it never enforced, allowing arbitrarily tiny trailing-window fragments on long sections. Trailing under-floor windows now merge into the previous window.

### Known issues (tracked in `BUGS.md`)
- Sliding-window sizing still uses word count as a token-count proxy, which undercounts badly on numeral-dense Table-of-Contents/Glossary/Index text.
- Open question: should front/back-matter (TOC, Glossary, Index) be filtered out of the retrieval corpus entirely?
- `SIZE_RATIO_THRESHOLD` (subsection-header font-size heuristic) is still an untuned constant.
- Printed page labels (roman numeral / chapter-relative) are classified but not yet wired into chunk metadata.
- Table extraction is unhandled and unverified against the real corpus.
