# Learning Notes — Ask My Docs (Aviation Handbook RAG)

Running, dated notes captured while building this project — the reasoning behind decisions, and concept explanations that came up along the way. Structural decisions themselves live in `.agent/decisions.log`; this file is for the *why* and *how it works*, in more depth than a one-line decision log entry.

---

## 2026-07-10 — Brainstorm: Architecture & Design

### Project in one paragraph
A production-shaped RAG (Retrieval-Augmented Generation) system over the FAA Airplane Flying Handbook. The retrieval→generation pipeline is the easy 20%; the eval harness, CI quality gate, citation verification, and observability are the point of the project — proving the system works, and catching it when it stops working.

### Repo structure & library choices (Build vs. Borrow)

Every component is "borrow" — a well-maintained library covers the need, no custom implementation:

| Component | Library | Reasoning |
|---|---|---|
| PDF parsing | `pymupdf` | Layout-aware block extraction, handles tables/figures better than plain text extractors. |
| Sparse retrieval | `bm25s` | Pure numpy/numba, no JVM dependency, speed comparable to Elasticsearch. |
| Dense embeddings | `sentence-transformers` (`bge-small-en-v1.5`) | Initially considered `fastembed` for its "fast" branding, but research turned up multiple reports of it being *slower* than sentence-transformers on CPU for MiniLM-class models — the name isn't a reliable signal on CPU specifically. Benchmark both on the actual dev machine before locking in. |
| Vector store | `lancedb` | Embedded (no server process), columnar format that scales past available RAM via disk-based indexing, built-in hybrid search + reranking support. Chroma is easier to start with but not meant for production-scale/p99-sensitive use; raw FAISS has no persistence or metadata filtering. |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` (default) or `bge-reranker-base` (config-swappable) | Both land ~130ms per 16-candidate batch on CPU — similar cost. MiniLM-L6-v2 is the more common default for speed/quality balance; bge-reranker-base is stronger but heavier. Since candidate/rerank counts are already config-driven, expose the model choice the same way. |
| Generation + judges | `anthropic` SDK | `claude-sonnet` for real answers, `claude-haiku` for eval judges (cheaper, run more often). |
| Tracing | `langfuse` | Cloud free tier (Hobby: 50k units/mo, 30-day retention) to start — simpler than standing up Docker on a single dev machine. Self-host later needs no code change since the tracer sits behind an interface. |

**Key lesson**: "Build vs. Borrow" isn't just "does a library exist" — it's "does the library's *actual measured behavior* match the claim," especially for anything CPU-performance-sensitive. `fastembed` marketing says fast; CPU reality is mixed. Benchmark, don't assume.

### Architecture

Modular pipeline, each stage independently swappable via config — this is what makes the acceptance criterion "disabling reranking visibly changes retrieval" possible: reranking isn't hardwired into the flow, it's a stage that can be no-op'd by config.

**Query-time flow** (every arrow below is also a traced span):
```
question
  ├─→ retrieval.bm25.search()   ─┐
  └─→ retrieval.vector.search() ─┴─→ fusion.rrf() → top-N candidates
                                                    → rerank.score() → top-k chunks
                                                    → generate.answer() → {text, citations}
                                                    → citations.verify() → {answer, citations, coverage}
```

**Offline flows** (not on the query path): `ingest` (PDF → chunks → indexes, run once/on re-chunk) and `eval` (golden dataset → metrics; cheap metrics on every push, expensive LLM-judge metrics nightly/manual only).

### Why hybrid retrieval (BM25 + dense) instead of just one?

BM25 (sparse/keyword) is precise for exact terms — V-speed names, regulation numbers, acronyms — but blind to paraphrase ("how much power to add" vs "throttle setting"). Dense embeddings capture semantic similarity but can miss exact rare-term matches that BM25 nails instantly. Reciprocal Rank Fusion (RRF) combines both *rankings* (not scores — scores from different systems aren't comparable, but rank positions are) into one list: `score(doc) = Σ 1/(k + rank_i(doc))` across each retriever's ranking. This is why RRF is standard for hybrid search — it sidesteps the score-normalization problem entirely.

### Why rerank after fusion, instead of just using fusion's top results?

BM25 and dense retrieval are both *fast but approximate* — optimized to scan the whole corpus quickly, not to deeply compare query-vs-candidate. A cross-encoder reranker takes the query and *each candidate chunk together* as one input (unlike bi-encoders, which embed them separately) — it's slower (can't precompute), but far more accurate at judging "does this chunk actually answer this question," which is exactly why it's only run on the already-narrowed top-N (20-30) rather than the whole corpus.

### Why citation "verification," not just formatting?

Asking an LLM to cite sources doesn't guarantee the citation is *correct* — the model can genuinely believe (or fabricate) that a claim is supported by a chunk it merely retrieved nearby. Verification is a second pass: for each cited claim, check whether the specific chunk it's attributed to *actually supports* that claim (LLM-judge or NLI-style entailment check). This is the difference between "grounding requested" (in the prompt) and "grounding checked" (verified after the fact) — the seed spec calls this out explicitly because it's the difference that matters for a safety-relevant domain.

### Why temperature=0 doesn't fully solve judge non-determinism

Temp 0 removes *sampling* (drawing randomly from a probability distribution) — the model just picks the highest-probability token every step (greedy decoding). That kills the *large* source of randomness. It does not guarantee bit-identical output across calls, because:

1. **Floating-point non-associativity in batched inference**: your request is processed alongside others in a batch on the provider's GPUs. Batch composition affects the order floating-point operations happen in, and floating-point math isn't associative (`(a+b)+c ≠ a+(b+c)` at the bit level in general). When two tokens have nearly equal probability, this tiny numerical noise can flip the argmax — and one flipped token cascades into a different rest-of-response.
2. **Backend infrastructure isn't static** — hardware/kernel/batch routing varies run to run; no provider contractually guarantees reproducibility even at temp 0.

**Consequence for this project**: expect eval metrics like faithfulness to wobble slightly (e.g. ±0.02-0.03) between identical runs on unchanged code. This is *why* the CI gate design uses **tolerance bands** (a metric within some range of baseline = pass) instead of a hard cutoff (any drop = fail) — a hard cutoff would flake the build on pure judge noise, not a real regression.

### Cost runaway — what it actually means here

Not "the app is slow," but "uncontrolled Anthropic API spend from a source other than one user asking one question." Specific sources in this pipeline:

- **Per-query multiplier**: one user question = 1 generation call + N faithfulness-verification judge calls (one per cited claim). A query can cost 3-5x more than its "one call" appearance suggests.
- **Eval-loop amplification**: a 50-150 question golden dataset × 2-3 judge calls per question (faithfulness, relevance, citation accuracy) = hundreds of calls per eval run. Running that on *every push* instead of nightly/manual turns normal commit activity into thousands of paid calls for changes that don't even touch answer quality.
- **No caching during iteration**: debugging the eval harness itself (not the pipeline) re-spends identically on unchanged inputs every re-run.
- **Retry storms**: an uncapped retry-on-failure can turn one rate-limit error into dozens of repeated calls.

**Mitigations**: cheap retrieval metrics (pure CPU, zero API cost) gate every push; expensive answer-eval is nightly/manual only; retries capped at 3 with backoff. Added during design: a **local response cache** keyed on `(question, config_hash)` so re-running eval during debugging doesn't re-spend on unchanged inputs, and a **daily running cost total** surfaced from Langfuse's per-request cost tracking (not just per-request — the aggregate is what actually catches runaway before the bill does).

### Inspecting the actual PDF before deciding chunking strategy — and why that mattered

Rather than guessing at chunk boundaries from the seed spec alone, I opened the real file with `pdftotext`/`pdfinfo` (poppler CLI tools — Python/PyMuPDF aren't installed in this environment yet, that comes with `/plan`'s setup step) and pulled real structural facts:

- **406 pages, 18 chapters + Glossary + Index**, confirmed against the actual table of contents — not assumed from prior knowledge of the handbook.
- **Single-column body text.** This matters because 2-column PDFs are a classic text-extraction trap: naive extractors read left-to-right across the *page*, interleaving the end of column 1 with the start of column 2 mid-sentence. Confirming single-column upfront means that failure mode isn't a risk here.
- **Dual page-numbering scheme**: front matter is roman numerals (i, ii, iii...), but the body uses *chapter-relative* labels like `4-1` (Chapter 4, page 1) — this is what real citations in the handbook look like, so it's what our citation format should mirror, rather than inventing our own page-numbering scheme that wouldn't match how a reader would actually look something up in the source document.
- **Chapter headers are regex-detectable** (`^Chapter N: Title$`), confirmed by grepping the extracted text — **but subsection headers are not**, because plain-text extraction throws away font size/boldness, and that's the only reliable signal distinguishing "this line is a heading" from "this line is a sentence that happens to be short." This is *why* the ingestion pipeline needs PyMuPDF specifically (which exposes font metadata per text span) rather than a simpler text-only extractor — a concrete case of a design decision driven by evidence, not by which library sounded fancier.
- **279 figure captions, 0 table captions.** The document is caption-rich for figures (`Figure 4-3. ...` appears as literal extractable text 279 times) but has no equivalent convention for tables — meaning tables in this handbook are either uncaptioned or rendered as flat images. This is a genuine open risk for ingestion quality that no amount of upfront design can fully resolve — it needs a manual spot-check against real table-heavy pages (V-speed reference tables, weight-and-balance charts) once the chunker is actually built, not just assumed to work.
- **CMap encoding warnings on nearly every page, but zero garbled characters found** in a full-text scan. This is a "trust but verify" situation: the PDF *reports* a font-encoding quirk, but the actual extracted text doesn't show corruption from it (no U+FFFD replacement characters). Recorded as a "verify again during implementation" item rather than either ignoring the warning or over-reacting to it.

**Key lesson**: "Propose the chunking strategy once you can see the actual PDF" (from the seed spec) isn't just process ceremony — the single-column confirmation, the chapter-vs-subsection heading detectability gap, and the missing table captions are all facts that would have been *wrong guesses* if chunking design had happened before opening the file. Real inspection changed two concrete decisions: the ingestion library (PyMuPDF for font metadata, not plain text extraction) and the citation page-number format (chapter-relative, matching the source document's own scheme).

---
