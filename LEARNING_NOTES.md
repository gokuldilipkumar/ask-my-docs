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

## 2026-07-13 — Building Block 4: two bugs no fast test could have found

### Mentioning content isn't citing it — a distinction the model needed spelled out
The first live-API test for the insufficient-context case failed: given one off-topic chunk and a question the excerpt didn't answer, the model correctly wrote an honest "the excerpt doesn't cover this" answer — but still listed that chunk in the structured `citations` field. The prompt said "cite by chunk id in square brackets" and separately said "say so honestly if you can't answer," but never told the model that *the citations field itself* must stay empty when nothing supports the answer. The model wasn't wrong given what it was told — it examined the chunk, referenced it in its explanation, and a citation-shaped field naturally absorbed that reference. Fixing this took two attempts: a first prompt edit ("don't cite chunks that don't answer, even to explain what they cover") still didn't work, because the model wasn't emitting a bracketed `[wb01]` citation in the *prose* — the `citations` field is a separate structured output the model fills independently of what it writes in `answer_text`. The fix that worked named the field directly: "the `citations` field... must be an empty list... even if you mention what an excerpt covers instead, mentioning it is not citing it." **Key lesson**: with structured outputs, a natural-language instruction about "citing in the text" doesn't automatically constrain a separate structured field — if a field has its own semantics, the prompt needs to address that field by name, not just the prose convention it's modeled after.

### A live spot-check found what 5 unit tests and 2 live-API tests didn't: a max_tokens ceiling
Every test written for Chunk 4.1–4.4 passed — including two real live-API tests. Then the Chunk 4.6 real-corpus spot-check, running all 8 design-doc sample questions end-to-end, crashed on question 6 ("What should a pilot do during upset prevention and recovery training?") with a bare `pydantic.ValidationError` three SDK frames deep: `EOF while parsing a string`. The model's answer for a genuinely detailed, multi-part question ran past `max_tokens=1024`, truncating the JSON mid-string. None of the earlier tests could have found this — they all used short, single-fact questions by design (that's what makes a fast, cheap, deterministic test). The failure mode only exists at the intersection of *real corpus content* and *a question broad enough to need a long answer* — exactly the gap synthetic and narrowly-scoped tests can't cover. This is the same lesson as Block 3's rerank-latency probe (short-string probes hid an 80x real-latency gap), applied to output length instead of input length: a test suite tuned for speed and determinism systematically under-samples the tail of real usage, and a spot-check across genuinely varied real questions is what catches it. The fix went through TDD anyway — a synthetic fixture reproducing the exact truncated-JSON string reproduced the crash before patching `generate_answer` to catch `ValidationError` and raise a clear, actionable `RuntimeError`.

### A raw dependency exception is not a contract — wrap it before your code depends on it
The uncaught `pydantic.ValidationError` bubbling up from three frames inside the `anthropic` SDK's own response-parsing internals is worse than a plain "answer failed" error: it names a class from a library the caller of `generate_answer` never imports, buried in a stack trace that looks like an SDK bug rather than a config problem. The fix — catch it and re-raise a `RuntimeError` that names `max_tokens` specifically — turns an opaque internal failure into an actionable one. The trade-off, logged honestly to `BUGS.md` rather than presented as a permanent fix: this catch is coupled to the *current* `anthropic` SDK version's internal exception type for this specific failure path. If a future SDK version changes how a parse failure surfaces, the catch silently stops firing. Fixing what's observable today is still worth doing, but a fix built on a dependency's internals is inherently more fragile than one built on that dependency's public contract — worth a comment saying so, so nobody mistakes today's fix for a permanent guarantee.

---

## 2026-07-13 — Auditing Block 4: the checklist that would have caught it didn't exist yet

### An example config file is invisible to every test, so nothing but a human (or a fresh-eyes review) catches it drifting
Chunk 4.1 fixed `config.yaml`'s stale `generation.model`; Chunk 4.2 added `max_tokens`/`timeout_seconds` and dropped `backoff_base_seconds` from both `settings.py` and `config.yaml`. Nobody touched `config.example.yaml` — a file that exists purely so a new developer has something to copy into their own `config.yaml`, and that no test, no `Settings` load path, and no CI step ever reads. It sat on the old shape (stale model name, a dead retry field, missing the two new ones) until the fresh-eyes entropy subagent happened to diff it against the real config and noticed. The general shape: any file whose only reader is a human copying it by hand is invisible to every automated check in the suite — it needs its own explicit audit-time diff, because nothing else will ever fail loudly on its behalf.

### A guard can be correct and still be a bug waiting to happen, if nothing proves it's there for a reason
`answer_question`'s `get_chunk_texts(...) if top_n_ids else {}` branch looks like defensive boilerplate — the kind of thing a reviewer might later "simplify" away as redundant, since `get_chunk_texts([])` *looks* like it should just return `{}`. It doesn't: probing it directly showed LanceDB rejects `WHERE chunk_id IN ()` as invalid SQL and raises a Rust-level parser error three layers removed from anything resembling "no chunks found." The branch was correct from the moment it was written, but had zero test coverage — nothing in the suite would have complained if a future edit deleted it, right up until the first real query returned zero retrieval hits in production. The earlier lesson from Block 3 ("untested defenses are bugs waiting") was about *speculative* insurance against unproven threats; this is the mirror case — *proven-necessary* insurance still needs a test, because "necessary" and "obviously necessary to the next reader" are not the same thing. Whether a guard is warranted and whether a guard is *legible* are two separate questions, and only a test answers the second one.

### The checklist only prevents what it already learned to look for
Both of the above were real findings, and neither was caught by any line in `audit.md`'s existing checklist — the config drift by simple omission (nobody had written "check the example file" because nothing had drifted like this before), the untested guard by a checklist gap (contract checks covered function signatures, not conditional branches). Both got added to `audit.md` this session via `/kaizen`. This is the same shape as the second audit's lesson about inherited generic checklists: a checklist doesn't fail by being wrong, it fails by not yet knowing about a failure mode this specific project hasn't hit yet. Every audit that finds something the checklist didn't ask about is an opportunity to make the checklist ask about it next time — which is the entire premise of compound engineering, applied to the audit process itself rather than to the code it reviews.

### Closeout's own workflow file was the same kind of stale template audit.md used to be
Reaching for `/closeout` surfaced a workflow file that still assumes `npm run lint && npm test && npm run build`, a `PROJECT_ROADMAP.md` that doesn't exist, README "Future Roadmap" sections to promote, per-phase git branches, GitHub Actions secrets, and a `/sync-workflows` step for a multi-repo setup this project doesn't have. Every actual closeout in this project's git history quietly ignored all of that and instead followed CLAUDE.md's own one-line description of the lifecycle — learning notes, changelog, project history, commit — because that's what this repo actually is. The file had simply never been kaizen'd, the same blind spot `audit.md` had until the 2026-07-13 audit rewrote it. A stale workflow file doesn't announce itself; it just sits there until someone tries to follow it literally and notices half the steps have no target to act on.

---

## 2026-07-14 — Building Block 5: verifying the verifier, and recovering from a crash

### An unplanned shutdown mid-build turned out to be a non-event — because git commits, not memory, are the real checkpoint
The previous session's `/build` was interrupted by the laptop losing power partway through Block 5. Recovery didn't need reconstructing what happened from memory: `git log` showed all five planned commits already landed in order, matching the plan file's chunk-by-chunk commit messages exactly, and the full test suite was still green (72 passed, 3 skipped). The only uncommitted state was the plan file's checkboxes and spot-check narrative — Chunk 5.6's manual findings, already written, just not yet `git add`ed. The general lesson: in a TDD workflow where every chunk ends in its own commit, a mid-session crash can only ever cost you the *current, uncommitted* chunk — never anything already checked in. The plan document itself doubles as a recovery log, since it records success criteria and findings as they're confirmed, not just as a pre-build design.

### A batched structured-output judge only proves its stripping path with an adversarial test, not an organic spot-check
`verify_citations` batches every citation in an answer into one Haiku call (`VerificationResult.verdicts: list[CitationVerdict]`) rather than one call per citation — cheaper and one round-trip regardless of citation count. The real-corpus spot-check (all 8 design-doc questions) landed at `coverage=1.0` on every single one: no citation was naturally stripped. That's not a failure of the judge — it's a consequence of Block 4's own prompt fix already doing most of the filtering upstream (the generation prompt was fixed last block specifically so the model stops citing chunks it didn't actually use). The only place the fail-safe stripping path was actually *proven* to work was Chunk 5.4's dedicated live-API test, built around a deliberately adversarial fixture (one clearly-supporting chunk, one clearly-irrelevant "FAA Wings Program" chunk paired with a stall question) — coverage dropped to 0.5 exactly as expected. **Key lesson**: a spot-check across real, non-adversarial usage tells you the system behaves well in practice; it does not tell you a specific failure-handling code path actually works, because well-behaved upstream inputs may simply never exercise it. Only a test built to *specifically* trigger the failure case proves the fail-safe fires — the same reasoning as Block 4's fail-loud `KeyError` guards, applied to a judge's negative case instead of a missing-data case.

### Fail-safe defaults for missing data are a different guarantee than "the judge said no"
`verify_citations` treats a verdict *missing* for a cited chunk_id the same as a verdict explicitly marking it unsupported — both strip the citation. This is deliberate, not an oversight: the block's entire contract is "every remaining citation is judge-confirmed," and a citation the judge never rendered an opinion on doesn't meet that bar, regardless of why the verdict is missing (a malformed model response, an id mismatch, anything). Defaulting an *absence* of information to the same outcome as a *negative* answer is the fail-safe pattern this project keeps reapplying (the RRF length-mismatch `ValueError`, `get_chunk_texts`'s fail-loud `KeyError`) — when a guarantee's whole purpose is catching bad data, "we don't know" must resolve to the same failure mode as "we know it's bad," never to the same outcome as "we know it's fine."

### Non-deterministic retrieval means a single spot-check can't distinguish "fixed" from "got lucky this run"
Block 4's spot-check found question 3 (short-field vs. soft-field takeoff) only answered half the comparison — a rerank surfacing gap, logged but deliberately not fixed pending Block 6's eval metrics. This session's spot-check re-ran the same question through the full verified pipeline and it answered *both* halves correctly. Tempting as it is to read that as the gap resolving itself, nothing in the pipeline between the two runs changed retrieval or rerank behavior — the only honest explanation is run-to-run variance in retrieval/rerank/generation (no fixed seed, no regression test pinning either outcome). Logged as a retrieval-variance note for Block 6, explicitly *not* reopened as fixed. This is the concrete case for why Block 6's eval harness exists at all: a single manual spot-check, however thorough, can't tell "the bug is fixed" apart from "this particular run didn't trigger the bug" — only a dataset run repeatedly against a metric can.

---

## 2026-07-14 — Building Block 6: the harness catches its first real bug on its first real run

### Ground truth has to come from somewhere other than the system being measured
Recall@k, MRR, and nDCG all need a "relevant chunk_ids" answer key — but where does that answer key come from? The naive approach (take whatever the current retrieval config ranks highest and call that "relevant") is circular: a config change that genuinely hurts retrieval quality could still score perfectly, because it would also be generating its own ground truth. The fix built this block runs `label_relevance` against a candidate pool *wider* than any single rerank config's output (`top_n=25` vs. `rerank.top_k=5`), and judges each candidate independently of its rank — so the labeling process can't just parrot back whatever the system already decided. The general shape: any evaluation ground truth that's derived from the same system it's meant to evaluate needs a structural reason it can't just be circular, not merely "we hope it's fine."

### An LLM-labeled draft plus a human review beats either extreme
Fully-manual labeling (read 25 candidates × 8 questions × zero LLM help) would have taken real time; fully-automatic labeling (trust the LLM's judgment with no review) would have shipped whatever biases the labeling judge has as unquestioned ground truth for every future eval run. What this block actually did — LLM-label the wide candidate pool, then read and correct the draft — turned an expensive from-scratch task into a cheap edit-and-approve one, without giving up the review step that makes the ground truth trustworthy. This surfaced two real, checkable findings in the process rather than nothing: q1's initial preview looked like it might be missing VSO-specific content (turned out a full-text check showed it wasn't — the preview was just truncated), and q4 turned out to have no "common errors" list anywhere in the 25-candidate pool at all, a genuine corpus gap rather than a labeling miss. Neither finding would have surfaced from either extreme — pure automation wouldn't have been checked, and pure manual work likely wouldn't have thought to audit the *full* candidate pool (not just the labeled-relevant subset) for a chunk that should have existed but didn't.

### The eval harness caught a fabrication bug that citation verification structurally cannot
Block 6's very first real end-to-end run found something Block 5's citation verification never could: for the crosswind-takeoff-errors question, the model answered "According to the handbook, the most common errors..." followed by eight specific numbered items, while citing exactly one chunk that contains no such list. Block 5's `verify_citations` judges *"does this cited chunk support something in the answer"* — and the single cited chunk (a real, relevant crosswind-technique excerpt) does, technically, support part of the answer. The problem isn't an unsupported citation; it's that the *prose itself* claims a direct-quote/enumerated-list authority the source material never had. This is exactly the boundary Block 5's plan named at the time as a stated limitation (Decision 6: "this block verifies only the citations the model already listed, not uncited claims in `answer_text`") — a limitation that sounded abstract when written and turned out, on the very first real eval run, to have a concrete instance. The lesson generalizes: a verification layer's scope boundary isn't just a caveat for the README — it's a prediction about the specific failure mode that will eventually slip through, and it's worth remembering exactly what that boundary was so the eventual failure is recognized immediately instead of investigated from scratch.

### Non-determinism isn't only a retrieval/rerank story — generation has it too, and now there's proof
Every earlier finding about query-to-query variance in this project (Block 4/5's question-3 short-field/soft-field gap) was attributed to retrieval or rerank, since neither Block 4 nor Block 6 pinned `GenerationConfig`'s temperature — it silently uses the Anthropic SDK's default. This block's first two runs of the *exact same question* (q1, VMC vs. VSO) scored `correct=True` on one run and `correct=False` on the very next, with the two generated answers genuinely differing in which VSO details they included — not a retrieval difference (the reranked candidate list was identical both times), a generation difference. This is direct, not inferred, evidence that answer *correctness itself* — not just which chunks get surfaced — varies run to run under this project's current settings. It's exactly why the design doc specified tolerance-band CI comparison instead of hard-cutoff pass/fail from the start: a single run's number was never meant to be trusted as ground truth about the system, only as one sample of a distribution the harness is now positioned to actually observe.

### A cache keyed on config can still go stale when the code changes underneath it
`eval/cache.py`'s `config_hash` hashes `Settings` fields (retrieval weights, model names, thresholds) on the theory that identical config should produce identical cached results. It does — for a fixed version of the code. Fixing `mrr`'s missing empty-relevant-ids guard mid-session didn't change any `Settings` field, so the existing cache entry for q8 would have kept silently returning the pre-fix `mrr=0.0` forever, with nothing in the cache's own logic able to detect the mismatch — it was only caught because the eval run happened again in the same session, right after the fix, and the number looked wrong by eye. A cache invalidation key is only as complete as the list of things it was built to detect changing; "the config didn't change" and "the answer is still correct" are not the same claim, and treating them as equivalent is exactly the kind of unstated assumption this project's audits keep existing to catch.

---

## 2026-07-15 — Auditing Block 6: composing a pipeline function can silently double its own cost

### Reusing a higher-level function isn't automatically cheap — it can hide a repeated expensive step
`eval/pipeline.py`'s `_evaluate_one` needed two things per golden question: retrieval metrics (which require the reranked candidate list) and a generated, verified answer (which Block 5's `answer_with_verified_citations` already produces end-to-end). The natural-looking way to get both was to call `hybrid_retrieve`+`rerank` directly for the metrics, *then* call `answer_with_verified_citations` for the answer — reusing an already-shipped, already-tested function instead of reimplementing generation. That instinct (call the existing composed function, don't reinvent it) is exactly what this project's own "Reuse Audit" convention has been training toward since Block 2. But `answer_with_verified_citations` doesn't take retrieved chunks as input — it retrieves and reranks *itself*, internally, from the question text. So the "reuse the existing function" call and the "compute metrics directly" call each independently paid the full retrieve+rerank cost, for the same question, in the same function, one call apart. Every test passed the whole time, because the mocked `hybrid_retrieve`/`rerank` fakes in `test_pipeline.py` cost nothing to call twice — the duplication was only ever expensive against the real corpus (rerank alone measured ~5.3s/query back in Block 3), and nothing in a fast unit-test suite can make an accidentally-doubled real-world cost visible. The general shape: reuse of an existing function is only actually cheap if that function's inputs don't overlap with work your own code already did — otherwise "don't reimplement it, just call it" quietly becomes "compute it twice."

### A self-declared threshold ("revisit at N") does nothing if nothing checks it
Block 4's audit found `tests/generate/test_client.py` hand-rolling the same `FakeClient`/`FakeScopedClient`/`FakeMessages` trio twice to fake `client.with_options(...).messages.parse(...)`, and logged it to `BUGS.md` with an explicit rule: "revisit if a third fake-client test appears." That rule is a promise about future code, not a check on it — and nothing in `/build` re-reads `BUGS.md` for standing thresholds before writing new test code. Block 6 wrote the *same* fake-client trio five more times across `test_judge.py` and `test_relevance.py` (both faking the identical `client.with_options().messages.parse()` shape, for the identical `EvalConfig` type) before anyone checked whether a threshold had already been crossed. The rule was correct; it just had no enforcement point. This is a small instance of a bigger pattern worth remembering: a debt note that says "fix this later, once X happens" is only as good as whatever process actually notices when X happens — writing the condition down is necessary but not sufficient.

### Fixing findings this session, then feeding them back into the workflow itself
Both of the above got fixed the same way the project always fixes an audit finding — TDD for the cost bug (a RED test asserting `hybrid_retrieve`/`rerank` are each called exactly once per question, which failed against the old code before the fix), straight extraction for the duplicated fakes (one shared `tests/eval/conftest.py` fixture). But `/kaizen` is where the *why didn't this get caught earlier* question gets asked, and both findings pointed at the same category of gap: `/plan`'s Reuse Audit checks "does an existing function cover this need" but never asks "does calling it duplicate work I'm already doing," and `/build`'s debt-discovery step logs new debt but never checks old debt notes for thresholds the new code might cross. Both are now explicit checklist items (`plan.md`'s Composition Cost Audit, `build.md`'s Threshold Check, plus a matching `audit.md` Composition Cost Check as a backstop) — not because either gap was exotic, but because a checklist bullet is a process that actually runs every time, and a lesson learned once in a session's narrative is not.

---

## 2026-07-15 — Building Block 7: a "safe default" that quietly wasn't

### Verifying a third-party SDK's real behavior turns a guess into a design
Langfuse's v4 SDK is OTel-based, and nothing about that is obvious from the function names alone — `start_as_current_observation` *sounds* like it might need a parent span id threaded through manually, the way older tracing libraries work. A five-line throwaway script (construct a client with fake credentials, open a span, open a second span nested inside the first `with` block, exit both) showed the real behavior directly: nesting is automatic via context propagation as long as both spans come from the *same* client instance, and the object yielded by `start_as_current_observation` has its own `.update(usage_details=, cost_details=, ...)` method for attaching results *after* the block already started. That one probe eliminated an entire category of plan-time uncertainty (how to attach token usage discovered only after the API call returns) and turned "the `Tracer` protocol should probably support something like an update method, we'll figure out the shape later" into an exact, confident signature before a single line of production code existed. The same probe also showed `Langfuse(public_key="fake", secret_key="fake", host="unreachable")` never raises on construction, and a failed span export logs a warning rather than propagating — meaning the wrapper code doesn't need its own defensive `try/except` around tracer calls, because the SDK already made that guarantee. Probing isn't just for catching wrong claims (Block 3's rerank-latency gap); it's often faster than reasoning from documentation to a design that's actually implementable.

### A parameter defaulting to "safe" and a parameter defaulting to "off" are different promises
`generate_answer`/`verify_citations` were designed so that omitting the new `observability` argument would be free — every existing caller and test keeps working, no Langfuse credentials required. That much held. What didn't hold, caught only because the test suite was re-checked against the *filesystem*, not just its own assertions: `noop_observability()`'s "safe" default still constructed a real `ObservabilityConfig()`, which carries a real `cost_db_path` and a real (if placeholder) price table — so even the untraced, no-observability code path still called `report_usage`, which happily wrote real rows to `data/daily_cost.sqlite3` on every single test run. Every assertion in every test still passed; nothing about the test suite's pass/fail signal revealed the problem. It surfaced only from `ls data/` after a green run — a side effect with no assertion pointing at it. The fix (gate cost recording on whether `observability` was *explicitly* passed, not on its defaulted value) is a small code change, but the lesson is really about what "safe default" has to mean: a default that's cheap to construct and doesn't raise is not the same guarantee as a default that has no side effects, and only the second one is actually safe to leave untested-against in every other call site.

### Sequencing a plan's own chunks is itself something worth getting reviewed
While finalizing last session's Block 7 plan, an early chunk (wiring `generate_answer`) referenced calling `hybrid_retrieve(..., observability=...)` from inside `answer_question`'s body — except `hybrid_retrieve` didn't gain that parameter until a *later* chunk. The plan would have been un-buildable in the order written: Chunk N's own code sample called a keyword argument that didn't exist until Chunk N+2. This was caught by re-reading the finished plan end-to-end looking specifically for forward references between chunks, not by any test (there's nothing to test yet — it's prose describing code that doesn't exist). The general check worth repeating for any multi-chunk plan: trace every cross-function call a chunk's sample code makes, and confirm the callee already has the shape that chunk assumes as of *that* chunk's position in the sequence, not the plan's final state.

---

## 2026-07-16 — Auditing Block 7: a capability can be fully tested and still never run

### "The parameter is tested" and "the parameter is reached" are different claims
Block 7 gave five already-shipped functions an optional `observability`/`observability_config` parameter, and every one of those five had a passing test proving the parameter worked when supplied. That's a real guarantee — but it's a guarantee about the *function*, not about the *system*. `eval/pipeline.py`'s `_evaluate_one` is the only real production caller of `generate_answer`, `verify_citations`, and `judge_answer` inside the eval harness, and it called all three with the parameter omitted — meaning every real Anthropic API call an eval run makes (and eval runs are, by cost, probably the single biggest consumer of API spend in this whole project — dozens of judge calls plus a full generate+verify pass per golden question) fell completely outside the daily cost cap this block exists to enforce. Nothing about this was subtle in the code once found: `_evaluate_one` simply never passed the new argument. It was invisible because "the tests pass" and "the feature works everywhere it should" answer two different questions, and a green test suite only answers the first one. The concrete habit this produced: after adding an optional parameter meant to extend *every* caller of a function, grep for every real (non-test) call site of that function and check each one by hand — not just the one the current plan's chunks happened to touch.

### A fresh-eyes review earns its cost by having zero stake in the story already told
The session's own build history described Block 7 as "additive-optional, every existing call site keeps working" — true, and reassuring, and also exactly the framing that makes "did every existing call site *start* using the new thing where it should have" invisible, because that question was never asked in that sentence. A subagent given only the changed files, no plan, no narrative, asked a plainer question — "does this composition actually wire cost tracking into the eval flow's real API calls" — and found the gap in one pass. This is the same shape as Block 6's "fresh-eyes subagent found a real Blocking issue nothing else caught" pattern repeating: a self-narrated summary of what a session did is a poor audit of what a session did, because the narration inherits whatever blind spot the session already had while writing the code.

### An unasserted spy is a coverage illusion, not coverage
Two tests (`generate_answer`, `verify_citations`) built a fake tracer that captured every `span.update(usage_details=..., cost_details=...)` call into a list — real infrastructure for a real assertion — and then never read that list. The tests looked thorough (custom fake tracer, dedicated test name, "opens a generation span and reports usage") and passed, but the actual claim in their own name — *reports usage* — was never checked. This is a distinct failure mode from a missing test: the scaffolding for the right assertion already existed, built by someone who clearly intended to check it, and the check itself just never got written. Worth remembering as its own audit-time question, separate from "is there a test": for every test double that records something, does *this specific test* look at what it recorded, or only that it was called at all?

---

## 2026-07-17 — Building Block 8: the same value, parsed two different ways, is two different values

### A local dev environment's leniency can hide a bug for the entire life of a project
`.env`'s `ANTHROPIC_API_KEY=` line has had a stray leading space since Block 4 — three blocks and dozens of real `live_api` test runs ago — and never once caused a visible problem, because `pydantic-settings`' dotenv source strips it silently when constructing `Settings()`. The first time that same file's value ever got read by something *other* than `pydantic-settings` — a raw shell pipe into `gh secret set` for Chunk 8.5's `nightly-eval.yml` secret — the space survived byte-for-byte into the GitHub secret, then into the `ANTHROPIC_API_KEY` environment variable inside the Actions runner, then into the `anthropic` SDK's HTTP header, where `httpx`'s `h11` backend correctly rejected it as an illegal header value (RFC 7230 forbids leading whitespace there) — surfacing three layers up the stack as an opaque `anthropic.APIConnectionError: Connection error`, with no mention of "space" or "header" anywhere in the top-level error message a first glance would see. The actual fix (`xargs` instead of `tr -d '\r\n'`) took two attempts because the first guess (Windows line endings, this project's usual CRLF suspect) was a reasonable prior that happened to be wrong — `xxd` on the raw bytes, not another guess, is what actually settled it. The general lesson: "this value has always worked" is a claim about one particular parser's tolerance, not about the value itself, and a value only becomes visibly wrong the moment something less forgiving reads it — which is exactly why a new consumer of old, unexamined data (a new CI job reading a long-stable `.env`, in this case) deserves suspicion even when nothing about *that new code* looks wrong.

### Verifying a workflow by pushing it beats reasoning about whether it's right
Both `cheap-gate.yml` and `nightly-eval.yml` were written carefully against everything already known about this project's test markers, config requirements, and CLI surface — and `cheap-gate.yml` passed on its very first real run regardless, while `nightly-eval.yml`'s actual bug (the `.env` space) was in a file that had nothing to do with this session's own changes and that no amount of re-reading the YAML would have surfaced, because the YAML was never the problem. This is the infra-equivalent of this project's now-familiar "a probe on real data beats reasoning from documentation" pattern (Block 7's Langfuse SDK probe, Block 3's rerank-latency claim) — a GitHub Actions workflow is itself a claim about a real environment, and the only way to verify a claim about a real environment is to run it in that real environment and read what comes back, not to trace the YAML by eye and declare it correct.

---
