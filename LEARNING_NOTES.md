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

## 2026-07-11 — Plan: environment, scoped planning, synthetic fixtures

### Why `uv` (and what it replaced)
This machine has no system Python at all — only the Windows Store stub aliases. `uv` was already installed and already had Python 3.11.8 provisioned, so it became the everything-tool: Python version management (replacing pyenv), virtualenv creation (replacing `python -m venv`), and dependency resolution with a lockfile (`pyproject.toml` + `uv.lock`, replacing `requirements.txt`). One tool, one lockfile, zero "which Python am I on" ambiguity. Every command in this project runs as `uv run <cmd>` — it transparently ensures the right interpreter and environment.

### The `src/`-layout, and why nothing needs `pip install -e .`
Packages live under `src/` (e.g. `src/ingest/`, `src/retrieval/`) rather than at repo root. The classic reason: with root-level packages, `import ingest` can accidentally resolve against the *working directory* rather than the installed package, hiding packaging bugs. The classic *cost*: you normally need an editable install for tests to find the code. The shortcut used here: pytest's `pythonpath = ["src"]` ini option injects `src/` onto `sys.path` for test runs only — no install step, no egg-info clutter. **The catch discovered later**: this only applies *inside pytest*. A manual `python -m app.main` doesn't get it, and needs `PYTHONPATH=src` set explicitly. Convenience shortcuts have scope; know where the scope ends.

### Scoped planning: full detail only for what you can see
The plan gives exact TDD test code for Block 0-1 only; Blocks 2-9 are sketched at block level. The reasoning: later blocks' test design depends on ingestion's *actual output shapes* (what a `Chunk` looks like, what real corpus statistics are), which don't exist yet. Writing exact test code against guessed schemas is designing against fiction — you'd pay twice: once writing it, once rewriting it. Plans should be detailed exactly as far as real information extends, and no further.

### Synthetic in-memory PDF fixtures
Ingestion tests build tiny PDFs at test time via PyMuPDF's own authoring API (`fitz.open()` + `insert_text(fontname="hebo")` — the built-in Helvetica-bold controls the bold flag). Rejected: checking in binary PDF fixtures. Why: in-memory fixtures are fast, deterministic, and *reviewable as plain Python* — a code reviewer can read exactly what the test document contains. The real 273MB handbook is gitignored and only touched by manual spot-check steps. (The limits of synthetic fixtures became a theme later — see the inline-bold bug below.)

---

## 2026-07-11 — Block 0+1 build: three library surprises and the inline-bold header bug

### Verify third-party APIs before writing tests against them
Three planned test designs turned out to assume library behavior that doesn't exist:
1. **pydantic-settings**: `YamlConfigSettingsSource` doesn't support a per-instance `_yaml_file` init-kwarg override the way `_env_file` does — the yaml path is fixed in `model_config` at class level.
2. **typer**: with only one `@app.command()` registered, typer silently collapses to *single-command mode* — the command name disappears from the CLI. `runner.invoke(app, ["ingest", ...])` fails until an empty `@app.callback()` forces multi-command mode. (That's why `main.py` has a no-op callback.)
3. **PYTHONPATH**: pytest's `pythonpath` ini doesn't apply outside pytest (above).

**Key lesson**: plan-time example code is a best guess, not a verified contract. A 5-line throwaway script that exercises the real library before writing the RED test costs a minute and prevents debugging a *test* while believing you're debugging *production code*. This became a permanent `/build` workflow step.

### The inline-bold header bug — synthetic fixtures encode your assumptions
The subsection-header heuristic was "bold and/or larger font ⇒ header." All 27 tests passed, because every synthetic fixture was built under the same assumption: bold text appears on its own line. The real FAA handbook bolds *inline field labels mid-sentence* ("**Rule #1:** If you want to move...", "**Throttle:** increase power..."). Every one of those was classified as a section header, fragmenting the corpus into 1,850 chunks with a **29-token median** against a 400-600 target — 60% of chunks under 50 tokens.

The fix: `TextSpan` gained `line_span_count` (how many spans share its physical PDF line), and a header must be the *sole content of its line*. Inline bold shares a line with surrounding text; true headers don't. Re-ingestion: 1,850 → 1,008 chunks, median 29 → 173.5 tokens.

**Key lessons**:
- A synthetic fixture can only fail in ways you already imagined. Real-corpus spot-checks are where unknown-unknowns surface — schedule them explicitly (Chunk 1.14 was exactly that, and it worked).
- When a real-corpus bug is found, the fix still goes through TDD: first a *synthetic fixture reproducing the failure* (a page with inline bold mid-sentence), watch it fail, then fix. That turns a one-off patch into a permanent regression guard.
- Corpus statistics (chunk count, median tokens, sub-50 share) are the observability layer for ingestion quality — a heuristic bug showed up as a *distribution shift*, not an exception.

### Word count is not a token count
The sliding-window fallback sized windows by word count as a proxy for tokens. On prose that's roughly fine; on numeral-dense text it fails badly — a 600-word chunk measured **1,275 actual tokens**, because BPE tokenizers explode strings like "9-37" into several subword tokens each. Words are a *lower bound* on tokens, and the gap is content-dependent, so a fixed word target can't enforce a token ceiling. (Still open debt — the real fix is trimming by actual `count_tokens()` measurement.)

---

## 2026-07-11 — First audit & kaizen: fresh-eyes review and compound engineering

### Why a zero-context reviewer catches what the author's tests miss
The audit spawns a subagent that sees *only the changed files* — no plan, no conversation history, no justifications. It found a real bug all 28 tests missed: `apply_sliding_window` accepted a `min_tokens` parameter it never referenced, so a long section's trailing window could be an arbitrarily tiny orphan fragment. Why did tests miss it? Because the author writes tests for the behaviors they were thinking about, and the author *thought* `min_tokens` was enforced — the same blind spot produces both the bug and the missing test. A reviewer without the author's context reads the signature and asks "where is this parameter used?" — a question the author never asks because they "know" the answer.

### Triage protects against reviewer over-eagerness
Review findings get bucketed: **Blocking** (fix now), **Improvement** (log as debt), **Nitpick** (acknowledge, skip). The judgment call worth remembering: a `dict.setdefault().append()` grouping pattern appeared three times, but across three *different value shapes* — extracting a generic `group_by()` would be premature abstraction, forcing three unrelated usages through one interface. Duplication count alone doesn't decide; whether the duplicates are genuinely the *same concept* does.

### Kaizen = encoding lessons into the process, not just remembering them
Both of this session's hard-won lessons (verify library APIs first; sample real corpus excerpts before writing synthetic fixtures for heuristics) were written *into the workflow files themselves*. The insight: a lesson in a human's (or model's) memory decays; a lesson in the checklist that every future session executes compounds. This is the "compound engineering" idea — the process improves itself as a side effect of doing the work.

---

## 2026-07-11 — Block 2: hybrid retrieval, and probe-verifying model-dependent tests

### The reuse audit: sometimes the right amount of new code is almost none
Block 2's plan started with a reuse audit and found Block 1 had already built everything retrieval needs (`search_bm25`, `search_vector`, index loaders). So the retrieval layer is two functions: `reciprocal_rank_fusion` (a pure function over ranked ID lists) and `hybrid_retrieve` (an orchestrator calling existing search functions). No wrapper modules, no adapter classes. YAGNI applied at the architecture level.

### Probe-verified fixtures: don't guess what a model will do
The plan's weight-flip test fixture assumed a keyword-stuffed chunk would win BM25 while a semantic chunk won vector search. At RED time, probing showed the embedding model *also* ranked the keyword-stuffed chunk first — the fixture didn't discriminate, and the test would have passed for the wrong reason. The replacement fixture was verified against the real models before the test was finalized: a semantic stall description vs. an off-topic keyword-"stall" chunk, with measured margins (BM25 0.46-vs-0.0 one way, vector 0.70-vs-0.60 the other).

**Key lesson**: any test assertion that depends on *model behavior* (embeddings, rankers) is a hypothesis, not a fact, until probed against the actual model. This is the retrieval-layer analog of "verify the library API first."

### Spot-checks generate evidence for deferred decisions
The Block 2 real-corpus spot-check did double duty: it confirmed fusion weights are load-bearing (flipping bm25/vector weights changes the #1 result on 2 of 3 sample queries — the design doc's acceptance criterion), and it produced the *first real evidence* on two questions deliberately deferred from Block 1: back-matter chunks were polluting top-5 results (decision: filter them), and V-speed queries surfaced nothing (new finding: subscript fragmentation). Deferring a decision until real signal exists, then collecting that signal deliberately, beats guessing early — but only if the deferred question is *logged* so it doesn't silently evaporate (`BUGS.md` did that job).

---

## 2026-07-12 — Ingestion fixes: geometric subscript joining and body-page-range filtering

### When the metadata lies, geometry is the fallback
The handbook typesets V-speeds as "V" plus a smaller subscript span ("MC", "SO"). PyMuPDF has a superscript/subscript flag — and it is simply *not set* on these spans. Probing real span data (before writing any fix) established the only reliable signal is geometric: the subscript is <0.8× the base font size, starts within 1pt of where the base span ends, and sits shifted below the base's top edge. The join happens at extraction time so "VMC" is intact everywhere downstream — chunks, indexes, citations. Rejected alternative: normalizing at the tokenizer/search layer, which would have fixed BM25 matching but left citation text reading "V MC".

**Key lesson**: extraction bugs should be fixed at extraction, not patched downstream — every downstream consumer (search, display, citations) inherits the fix for free. And: probe the real data *first*, then write the synthetic RED fixture to match verified reality (the fixture reproduces the flag-not-set behavior because we checked; a guessed fixture might have set the flag and tested a fantasy).

### Order of operations matters: filter before detect
Front/back matter wasn't just low-value retrieval content — it was *corrupting structure detection*. TOC pages repeat "Chapter N: Title" lines verbatim, so every chapter header was detected twice (once at its real page, once in the TOC); Index/Glossary alphabet headings ("V", "S") and page-number labels fragmented back matter into ~330 junk sections (chapter 18 alone held 402 of 951 chunks). That's why the filter drops spans *before* header detection rather than dropping chunks after chunking — filtering after would leave the duplicate chapter anchors and fragmented sections in place. The page range (21-390) lives in `config.yaml`, not code: it's a fact about *this corpus*, not logic. Glossary kept (real definitional content — a glossary chunk now answers the VMC/VSO query); TOC and Index dropped.

Corpus after both fixes: 951 → 617 chunks, median tokens 173.5 → 329, sub-50-token share 33% → 8%.

### Repo config can poison tests
Adding the corpus-specific page range to `config.yaml` broke the CLI tests: they invoke the real `ingest` command, which reads the repo's `config.yaml` (cwd-relative), whose page range 21-390 filtered the 1-2 page synthetic test PDFs down to *zero* chunks. Fix: the tests chdir into a tmp dir with a minimal config. **Key lesson**: any config key whose *value* is corpus- or environment-specific will leak into every test that implicitly reads the repo config — isolate those tests the moment such a key is introduced (now a `/build` workflow rule).

---

## 2026-07-13 — Second audit & kaizen: silent-contract bugs and false comments

### The silent-truncation bug class
`reciprocal_rank_fusion` iterated `zip(rankings, weights)`. Python's `zip` stops at the *shorter* input — so a weights list shorter than the rankings list would silently drop entire rankings from the fusion. Concretely: a mis-sized config could turn "hybrid retrieval" into single-index retrieval with no error, no log, no failing test — just quietly worse results. The fix is one word (`strict=True`, Python 3.10+), which makes the mismatch raise `ValueError`.

The deeper point: Block 2 wrote four tests for this function, all passing, none catching this — because all four tested *planned behavior* (fusion math, weighting effects). Contract violations (mismatched parallel inputs, empty inputs, unused parameters) are a different category that happy-path TDD systematically misses, and this is the *second consecutive audit* to find one (the dead `min_tokens` parameter was the first). Hence the new `/build` rule: every chunk's RED tests include at least one contract case, and prefer APIs that fail loudly over ones that silently degrade.

### Comments are claims, and claims can be false
A comment in the windowing code read "word count is an upper-bound proxy; count_tokens gates the real limit" — wrong on both halves (word count is a *lower* bound on tokens; `count_tokens` doesn't gate split windows at all). It was written during the *previous audit's own fix* and survived that audit's review. A false comment is worse than no comment: it actively teaches the next reader the wrong model. New audit rule: comments making factual/quantitative claims get verified against the code like any other artifact.

### Checklists should encode *your* failure classes
The `/audit` workflow file turned out to be an inherited template from a different stack — npm/Vitest/Supabase/React checks, a grep of a file that doesn't exist, a pointer to a nonexistent reference doc. Every audit paid a mental filtering tax. The kaizen rewrite replaced it with checks derived from *this repo's actual observed failures*: contract checks (dead params, strict zip), comment integrity, index-rebuild-after-schema-change, corpus spot-checks. **Key lesson**: a checklist is only compound-engineering if it encodes what *this* project actually gets wrong; a borrowed checklist encodes someone else's history.

---

## 2026-07-13 — Block 3: cross-encoder reranking

### Designing a bug class out of existence
The RRF zip bug (silently dropped rankings when parallel lists mismatched) got a `strict=True` guard — a *runtime* defense. Block 3's `rerank()` went one better: candidates are `(chunk_id, text)` **pairs**, so there are no parallel lists to mismatch. The lengths can't disagree because there's only one list. Guard-rails catch a bad state at runtime; API shape can make the bad state *unrepresentable*. When you find a bug class, ask whether the next API you design can exclude it structurally rather than defensively.

### Untested defensive code is where silent bugs live
The probe had just demonstrated that LanceDB plain filter scans have no default row cap. I added `.limit(len(chunk_ids))` anyway — "cheap insurance." That line became the bug: the table holds duplicate chunk_ids, duplicates inflated the match count past the limit, and the scan silently truncated before reaching later rows. The insurance *caused* the exact failure mode (silent truncation) it vaguely gestured at preventing. Two lessons stacked here:
1. Defensive code is still code — it can be wrong, and because "it's just insurance," nobody writes a test for it, which is precisely why its failures are silent.
2. A defense against a threat your own probe just disproved isn't caution, it's superstition. Either the threat is real (then probe it and test the defense) or it isn't (then the defense is untested complexity).

### A designed invariant nobody counts is a hope, not an invariant
"Content-hash chunk IDs are stable and unique" was a design cornerstone from day one — citations, golden-dataset references, and re-ingestion stability all lean on it. It was also false for two whole blocks: 617 chunks, 590 unique IDs, with one ID shared by *five different chunks* (the handbook repeats section titles like "Common errors..." per maneuver within a chapter, and the hash input — chapter, title, sequence — can't tell them apart). Nothing caught it because nothing counted: no ingest-time assertion, no test, no spot-check ever compared row count to unique-ID count. The check is one line of Python. **Key lesson**: every invariant a design *states*, some artifact must *verify* — an uncounted invariant isn't guaranteed by the elegance of the scheme that's supposed to produce it. (Found only because `get_chunk_texts` fails loud: the KeyError from the limit bug forced the diagnosis that exposed the duplicates.)

### Fail-loud contracts find other people's bugs too
`get_chunk_texts` raises `KeyError` when a requested ID isn't found, rather than returning what it has. On its very first real-corpus contact, that KeyError fired — and the investigation it forced uncovered both the limit bug (mine, hours old) and the duplicate-ID bug (ingestion's, two blocks old). A lenient version returning partial results would have run "fine": the reranker would have quietly scored 16 of 20 candidates, results would look plausible, and both bugs would have survived into Block 5's citations. Silent degradation doesn't just hide its own bug — it hides every upstream bug whose symptom it swallows.

### Performance probes must use production-shaped inputs
The design doc claimed ~130ms per 16-candidate rerank batch. My API probe measured 63ms/16 — claim confirmed, ship it? Real corpus: **5.3 seconds** per 20-candidate query, an ~80x gap. The probe used short strings; real chunks have a 329-token median, and transformer inference cost grows steeply with sequence length (attention is quadratic in it). The probe verified the API contract but *invalidated nothing about the claim*, because the claim was only ever false at production lengths. Bonus trap discovered in the same investigation: the cross-encoder silently truncates input past 512 tokens, so oversized chunks (the open windowing debt) aren't even fully scored — two debts interacting invisibly.

### (Later same day) The fail-loud chain, three layers deep
Fixing the duplicate-chunk-id bug demonstrated why fail-loud beats fail-soft *in sequence*: (1) `get_chunk_texts`'s KeyError exposed the scan-limit bug; (2) diagnosing that exposed the duplicate IDs; (3) the new ingest-time collision check — written for the ID fix — fired on its very first real run and exposed a *third* bug: glossary V-speed notation leaves stray standalone "V" spans whose text equals the page's alphabet heading, and text-equality header matching spawned five bogus sections. Each guard found the next bug. Also note: that third bug had been logged as "latent (not observed on this corpus)" during the audit — it *was* observable all along; nothing was looking.

### Choosing a disambiguator is choosing what stays stable
`page_index_start` beat a per-chapter occurrence counter for the chunk-id hash because of *what survives change*: if header detection improves and finds one more section early in a chapter, every later same-title section's occurrence index shifts (breaking their IDs), while start pages don't move. When picking identity inputs, ask "what edits will happen to this system, and which candidate inputs are invariant under them?" — not "which is easiest to compute."

### Match by signature, not by string
The header-matching fix generalizes: when a detector identifies *specific items* (header spans) and a later stage needs to recognize those same items in a stream, matching by the item's text alone re-derives identity from the weakest attribute. Carrying more of the signature (text + font size + boldness) — or ideally a real reference — prevents impostors that happen to share the string. The corpus contained natural impostors nobody predicted: subscript fragments matching single-letter glossary headings.

### Truncation-on-disabled: contract stability beats purity
`enabled=False` still truncates to `top_k` rather than being a byte-pure passthrough. Argument for purity: "disabled means the stage does nothing." Argument for truncation: downstream consumers get "at most top_k chunks" as an *invariant of the function*, regardless of a config toggle — a generator prompt built for 5 chunks never suddenly receives 20 because someone A/B'd the reranker. When a stage can be toggled off, decide which of its output guarantees survive the toggle, and keep the ones downstream code depends on.

---

## 2026-07-13 — Auditing the chunk-id fix: verify claims, don't relay them

### "The log says it's true" is not the same as verifying it's true
The previous session's `PROJECT_HISTORY.md` entry already claimed "612/612 unique ids in both indexes, id sets identical" and a working crosswind spot-check. It would have been easy to treat that as settled and move straight to `/plan` Block 4. Instead this audit re-ran both checks independently — reading the actual index files (`corpus_ids.json` for BM25, a live `table.search().to_list()` scan for LanceDB) and re-issuing the crosswind/VMC queries through `hybrid_retrieve`. They matched the log, which is the good outcome, but the point of an audit is that this was earned, not assumed. A session's own notes about its own work are a claim, not a proof — the same standard this project applies to LLM-generated citations (verify against the source chunk) applies to *human/agent-generated session notes* about test results.

### A clean audit is still worth running
This audit produced zero Blocking findings and no code changes — just two Low debt items from a fresh-eyes review. It would have been reasonable to skip it and go straight to planning Block 4. The value wasn't in finding a bug; it was in *confirming* the chunk-id fix's claimed invariants hold under independent re-check before building three more blocks (generation, citations, eval) on top of them. An audit that finds nothing isn't a wasted audit if it was the first time the claim was checked by someone (something) other than the code that's supposed to satisfy it.

### Practical note: manual CLI checks need `PYTHONPATH=src` and a placeholder API key
Re-running the spot-check outside pytest required two environment details this project's own `/audit` workflow already documents but are easy to forget in the moment: `PYTHONPATH=src` (pytest's `pythonpath` ini option doesn't apply to a bare `python -c`), and `ANTHROPIC_API_KEY` must be set (even a placeholder) because `Settings()` validates it as a required field at construction time — unrelated to what the query itself needs.

---

## 2026-07-13 — Planning Block 4: catching a stale default before it shipped

### A "verify at build time" comment is a debt ticket, not documentation
`GenerationConfig.model` read `claude-sonnet-4-5` with a comment saying to verify it against the current model list at build time — written back when the design doc was drafted, before this session had access to a current model catalog. It would have been easy to read the comment as already-satisfied documentation and move on. Comments that say "verify this later" are a promise, not proof the verification happened; this session's model-provider knowledge made it possible to actually redeem that promise now, so the fix went into the plan (Chunk 4.1) instead of getting deferred a second time. Same failure shape as the false-comment lesson from the second audit: a claim sitting in the codebase is only as good as the last time someone actually checked it.

### Structural safety over runtime discipline, applied a third time
Block 2 guarded against a parallel-list mismatch with `strict=True` (runtime defense). Block 3 made the bug structurally impossible by passing `(id, text)` pairs instead of parallel lists. Block 4 extends the same instinct one layer up the stack: instead of hand-writing a prompt asking Claude to emit JSON and then parsing it hopefully, `client.messages.parse(output_format=GeneratedAnswer)` makes a malformed citation list a validation error the SDK raises, not a string the app has to defensively re-parse. Three blocks in a row, the same question paid off: can the invalid state be made unrepresentable instead of merely checked for?

### A config field can be dead before it's ever used
`backoff_base_seconds` existed in `GenerationConfig` since the original design doc, intended for hand-rolled retry backoff — but the Anthropic SDK already retries 429/5xx with its own exponential backoff via `max_retries`. Adopting the SDK-native retry made `backoff_base_seconds` genuinely unused from the moment `generate_answer` was designed, not after some later refactor. The two prior audits found *dead parameters* after the fact (a `min_tokens` argument nothing read, a config field nothing checked); this time the plan caught it *before* the field was ever wired to anything, by asking "what does this number actually control?" while deciding the retry strategy — cheaper than fixing it in a third audit.

### Resolving debt without touching the code that created it
Block 3's plan flagged a "double fetch" problem — the reranker needs chunk text to score candidates, and the generation prompt needs chunk text again for the (smaller) reranked set — and explicitly punted the decision to Block 4. The resolution didn't require changing `rerank()` at all: since reranking only ever *narrows* a candidate list, the orchestrator can keep the original `get_chunk_texts` dict in memory and look up the final ids in it, rather than querying the index a second time or changing `rerank`'s already-tested contract. When a later block owes a decision about an earlier block's design, check whether the fix belongs in the new orchestration layer before reopening code that already shipped and passed review.

---
