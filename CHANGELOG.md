# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- `uv`-managed Python 3.11 project scaffolding (`src/`-layout packages: `ingest`, `retrieval`, `rerank`, `generate`, `citations`, `eval`, `observability`, `config`, `app`).
- Config-driven `Settings` (pydantic-settings): `config.yaml` + `.env` layering, required-secret validation, no magic numbers — chunk size, RRF weights, rerank/citation/eval thresholds all config-driven from the start.
- PDF ingestion pipeline (PyMuPDF): text-span extraction with font metadata, chapter-header detection, subsection-header detection (font-size/bold, sole-line-placement), figure-caption extraction, deterministic content-hash chunk IDs, subsection-boundary-first chunking with a token-aware sliding-window fallback (400-600 tokens, 15% overlap) for oversized sections.
- BM25 sparse index (`bm25s`) and vector index (LanceDB + `bge-small-en-v1.5`) build/search, both with build→reload→search round-trip tests.
- `ingest` CLI command (typer) wiring the full pipeline end to end.
- Ingested the real FAA Airplane Flying Handbook (406 pages): 617 chunks across both indexes (after front/back-matter filtering; was 1,008 at first ingest).
- Hybrid retrieval (Block 2): `reciprocal_rank_fusion` (config-weighted RRF, pure function) and `hybrid_retrieve` orchestrating the existing BM25 + vector search; real-corpus spot-check confirms flipping fusion weights via config visibly reorders results (design-doc acceptance criterion).
- Config-driven body page range (`chunking.body_page_start`/`body_page_end`): spans outside the body range are dropped before header detection. For this corpus (21-390): front matter/TOC and the back-of-book Index are excluded; the Glossary is kept as retrievable definitional content.
- Cross-encoder reranking (Block 3): `rerank()` scores `(query, chunk_text)` pairs with a config-named cross-encoder (`rerank.model`, default ms-marco-MiniLM-L-6-v2) and truncates to `rerank.top_k`; `enabled=False` is a passthrough that preserves fused order and provably never loads the model. Candidates travel as `(chunk_id, text)` pairs — no parallel lists to mismatch. Real-corpus spot-check: toggling rerank changed the top-5 on all three sample queries, demoting a keyword-soup V-speed-list chunk off the VMC/VSO top-5 in favor of actual VMC content.
- `get_chunk_texts(db_path, chunk_ids)`: id→text lookup on the existing LanceDB table (the reranker's join between `hybrid_retrieve`'s IDs and scoreable text); raises `KeyError` on missing IDs rather than silently returning partial results.

### Fixed
- Subsection-header detection was misclassifying inline bold emphasis (e.g. "**Rule #1:** ...") as standalone headers, fragmenting 60% of real-corpus chunks to under 50 tokens against a 400-600 target. Headers now require sole-line placement, not bold/size alone. Re-ingestion: 1,850 → 1,008 chunks, median chunk size 29 → 173.5 tokens.
- `apply_sliding_window` accepted a `min_tokens` floor it never enforced, allowing arbitrarily tiny trailing-window fragments on long sections. Trailing under-floor windows now merge into the previous window.
- V-speed subscripts ("V" + smaller "MC"/"SO" spans, extracted separately by PyMuPDF with no superscript flag set) fragmented terms like "VMC" and broke BM25 matching for V-speed queries. Subscript spans now join their base span geometrically; "VMC" survives extraction intact in 62 spans (was 0).
- TOC pages repeat "Chapter N: Title" lines verbatim (duplicating every detected chapter header) and Index/Glossary headings fragmented back matter into ~330 junk sections that polluted retrieval top-5s. Fixed by the body-page-range filter above. Corpus quality after both fixes: 951 → 617 chunks, median tokens 173.5 → 329, sub-50-token share 33% → 8%.

- `reciprocal_rank_fusion` silently dropped rankings beyond the weights list length (`zip` without `strict=True`) — a mis-sized config would quietly turn hybrid retrieval into single-index retrieval. Now raises `ValueError` on length mismatch. Found by the audit's fresh-eyes review; Block 2's four happy-path tests all passed over it.
- `get_chunk_texts`'s scan limit silently truncated results when the table holds duplicate chunk_ids (its fail-loud KeyError caught this on first real-corpus contact); chunk IDs are now SQL-escaped in the LanceDB filter string so no ID can corrupt the query.

### Known issues (tracked in `BUGS.md`)
- Sliding-window sizing still uses word count as a token-count proxy, which undercounts badly on numeral-dense text; 143 of 617 chunks exceed 650 tokens.
- `SIZE_RATIO_THRESHOLD` (subsection-header font-size heuristic) is still an untuned constant.
- Printed page labels (roman numeral / chapter-relative) are classified but not yet wired into chunk metadata.
- Table extraction is unhandled and unverified against the real corpus.
- `Settings` loads `config.yaml` relative to the cwd — running the CLI outside the repo root silently skips the corpus body-page-range filter (plus six smaller entropy items from the 2026-07-13 audit).
- **Duplicate chunk IDs in the real corpus (HIGH)**: 617 chunks, 590 unique IDs — `make_chunk_id(chapter, title, sequence)` collides on section titles the handbook repeats per maneuver ("Common errors..." ×5 on one ID). Breaks citation uniqueness and golden-dataset references; must be fixed (hash disambiguator + re-ingest) before Block 5.
- Rerank latency on real chunks is ~5.3s per 20-candidate query on CPU (design claim of ~130ms holds only for short passages); chunks past the model's 512-token input limit are silently truncated during scoring. Block 4 decision item.
