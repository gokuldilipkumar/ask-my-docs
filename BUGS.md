# Technical Debt / Known Shortcuts

Tracked per `.agent/workflows/plan.md` "Technical Debt Strategy" and surfaced during `/build`.
Format: `- [ ] <item>` — check off and remove once resolved, noting the fix in `PROJECT_HISTORY.md`.

## Ingestion (Block 1)

- [ ] `SIZE_RATIO_THRESHOLD = 1.15` (`src/ingest/headers.py`) is an untuned guess, not validated against the real handbook's actual font-size distribution. Validate/tune during Chunk 1.14's manual spot-check run.
- [ ] `detect_subsection_headers`'s body-font-size heuristic (`Counter(sizes).most_common(1)`) resolves ties by insertion order, discovered while writing Chunk 1.3's tests: a page/section with very few body-text lines relative to header lines can misclassify the body size, causing a real header to be skipped as body text. Real handbook pages have far more body text than headers so this is expected to be rare in practice, but Chunk 1.14's spot-check should specifically look for sections that seem to be missing their header.
- [ ] `classify_page_label` (`src/ingest/page_labels.py`, Chunk 1.4) matches on text shape only, not footer position — not wired into `chunk_pdf`'s `printed_page_label` field yet. Needs a bbox-based "near bottom of page" check before it's trustworthy enough to surface in citations.
- [ ] Table extraction is unhandled — the design doc found zero `Table N-N.` caption matches anywhere in the corpus. No table-specific handling exists; Chunk 1.14's manual spot-check on weight-and-balance/V-speed reference pages is the first real signal on whether this is a problem.
- [ ] Sliding-window fallback (Chunk 1.9) sizes windows by word count as a token-count proxy, not an exact token boundary — `count_tokens` gates whether windowing triggers at all, but doesn't guarantee every individual window lands inside `[min_tokens, max_tokens]` precisely.
