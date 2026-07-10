# Build Prompt — Production-Grade Domain RAG System ("Ask My Docs")

## Role & goal
You are building a **production-shaped, domain-specific RAG system** — not a demo. I ask questions over a private document corpus and get **grounded answers with verifiable citations**. The project's real value is in what surrounds the pipeline: **hybrid retrieval, cross-encoder reranking, citation verification, an evaluation harness with a CI quality gate, and full tracing/observability.** Treat those as first-class requirements, not afterthoughts. The system building is ~20% of the work; **knowing whether it works — and catching when it regresses — is the other 80%, and that is the point of this project.**

## Corpus
- **FAA Airplane Flying Handbook (FAA-H-8083-3C)** — a public-domain FAA PDF, several hundred pages, with chapters/sections, figures, tables, and diagrams interleaved with prose.
- Domain is safety-relevant and term-dense (V-speeds, aircraft systems, maneuver names, regulatory references) — good stress test for hybrid retrieval and citation verification specifically because a wrong or uncited answer here would matter in real life.
- Ingestion should skip/handle image-only content gracefully and **carry chapter/section title in chunk metadata**, not just page number — citations should read like "Ch. 4: Energy Management, Slow Flight," not just a page number. This is worth getting right early since re-chunking later means re-running ingestion + eval.
- Everything else about the eval questions, exact chunking parameters, etc. can be figured out once you're looking at the actual PDF structure — propose it then rather than guessing now.

## Target environment
- OS: Windows 10/11 (dev), Linux for CI runners.
- CPU: 12th Gen Intel Core i7-1255U (10 cores / 12 logical). **CPU-only, no NVIDIA GPU.** Every local model (embeddings, reranker) must run on CPU. The **generation step calls the Anthropic API** (`claude-sonnet` for quality, `claude-haiku` for cheap eval loops) — do not run a local LLM.
- Language: Python 3.11+.
- Keep all secrets (Anthropic API key, Langfuse keys) in `.env` locally and GitHub Actions secrets in CI. Never commit them.

## Core pipeline (build end to end first)
1. **Ingestion & chunking**: load the FAA Airplane Flying Handbook PDF. Chunk with overlap, and attach **stable, deterministic chunk IDs** plus metadata (chapter, section title, page). The IDs must survive re-ingestion so citations and eval references stay valid. Handle figures/tables/diagrams gracefully — don't let table layout or image captions turn into garbled chunk text.
2. **Hybrid retrieval**:
   - **Sparse (BM25)** over the chunk text (e.g. `bm25s` or `rank_bm25`).
   - **Dense (vector)** using a small CPU embedding model (e.g. `bge-small-en-v1.5` via `sentence-transformers`/`fastembed`), stored in FAISS-cpu / LanceDB / Chroma.
   - **Fuse** the two rankings with **Reciprocal Rank Fusion (RRF)** (configurable weights). Return top-N candidates.
3. **Cross-encoder reranking**: rerank the top ~20–30 fused candidates with a **small CPU cross-encoder** (e.g. `bge-reranker-base` or a MiniLM ms-marco cross-encoder). Budget a few hundred ms to ~2s; keep the reranked set small (top 4–8) for the generation context. Make candidate counts configurable.
4. **Grounded generation**: pass reranked chunks (each tagged with its stable source ID) to the Anthropic API. The prompt instructs the model to answer **only from provided context** and to **cite by source ID**. If context is insufficient, it must say so rather than hallucinate.

## Citations & source grounding (verification, not just formatting)
- Return answers with inline citations that map to **stable chunk IDs**, resolvable back to source file + location.
- **Faithfulness verification pass**: after generation, verify each cited claim is actually supported by the chunk it cites (LLM-judge or NLI-style check). Flag or strip unsupported citations. This verification is a core deliverable — "grounding" means *checked*, not *requested*.
- Compute **citation coverage** (fraction of answer claims backed by a verified citation) and expose it per response.

## Evaluation harness (the real work — do not shortcut)
- **Golden eval dataset**: (question → expected relevant chunk IDs), and where feasible a reference answer. You may **bootstrap** questions by generating Q&A from the corpus, but the dataset must support **human review/curation** — mark auto-generated vs. reviewed items, because a self-graded set is circular. Include some deliberately close/confusable questions (e.g. distinct V-speeds or similar-sounding maneuvers) — good stress test for whether reranking is actually doing anything.
- **Retrieval metrics** (cheap, deterministic, pure CPU): Recall@k, MRR, nDCG against the golden chunk IDs.
- **Answer metrics** (LLM-judge, via API): faithfulness/groundedness, answer relevance, citation accuracy. Run judges at **temperature 0**.
- Establish a **baseline** from a first full run so thresholds aren't arbitrary. Store eval runs with the git commit + prompt version they ran against.

## CI quality gate (deployment gating on metrics)
- **GitHub Actions** workflow. On every push/PR: run the **cheap retrieval metrics** and fail the build if they drop below threshold vs. baseline.
- Because LLM-judge metrics are **non-deterministic**, do NOT use a naive hard cutoff: use **tolerance bands** (or average over N runs) so a 0.82→0.79 wobble on unchanged code doesn't flake the build.
- Because API calls cost money per run, gate the **expensive answer-eval** behind a **manual/nightly workflow** (not every push). API key lives in GitHub Actions secrets.
- Emit a summary (metrics vs. baseline, pass/fail per metric) into the CI run so a reviewer sees *why* it passed or failed.

## Monitoring & Observability (first-class — this is the differentiator)
- **Tracing**: instrument **every pipeline step** as spans — ingestion is out of band, but per query: retrieve(sparse), retrieve(dense), fuse, rerank, generate, verify. Use **Langfuse** (open-source, self-hostable via Docker on your machine, or its free cloud tier). Keep the tracer behind a thin interface so **LangSmith or Braintrust can be swapped in** without touching pipeline code.
- **Metrics tracked per request**: **latency at p50 and p95** (overall and per stage), **cost per request** (token usage × model price for the generation + judge calls), **citation coverage**, and **failure rate** (errors, empty retrievals, insufficient-context answers). Surface these as aggregates over a time window.
- **Prompt versioning — version prompts like code**: store every prompt template with a version identifier (in-repo files under git, and/or Langfuse prompt management). Each trace and each eval run records **which prompt version produced it**, so you can attribute a metric change to a specific prompt edit.
- **Deploy gating on eval metrics**: a "promotion" step that only marks a prompt/config version as deployable if its eval metrics clear the gate — tying the prompt version, the eval run, and the observability data together into one auditable chain.

## Architecture
- Modular packages: `ingest`, `retrieval` (bm25, vector, fusion), `rerank`, `generate`, `citations` (formatting + verification), `eval` (dataset, metrics, judges), `observability` (tracer interface, cost/latency instrumentation), `config`, `app` (CLI and/or a thin API/UI).
- **Config-driven**: chunk size/overlap, embedding model, vector store, RRF weights, candidate/rerank counts, models, thresholds — all in config, no magic numbers in code.
- Deterministic where it can be (temp 0 for judges); seed anything random.

## Suggested libraries (pick a reliable set and justify briefly)
`bm25s`/`rank_bm25` (sparse) · `sentence-transformers`/`fastembed` (embeddings + cross-encoder) · `faiss-cpu`/`lancedb`/`chromadb` (vector store) · `anthropic` (generation + judges) · `langfuse` (tracing) · `pydantic` (schema/validation) · `pytest` (tests) · a light CLI (`typer`) and optional thin UI (`streamlit`/`fastapi`). Flag anything heavy on CPU.

## Non-goals (keep it focused)
No local LLM inference, no GPU dependency, no multi-tenant auth, no huge web frontend. A clean CLI (plus optional minimal UI) is enough. No fine-tuning here — this is retrieval + generation + evaluation + observability.

## Deliverables
1. Working, modular code matching the architecture above.
2. Ingestion of the FAA Airplane Flying Handbook (script + the PDF or a documented download step) so the whole thing runs out of the box.
3. The **golden eval dataset** (with the auto-vs-reviewed flag) and the eval harness.
4. **GitHub Actions** workflows: cheap retrieval gate on push; nightly/manual answer-eval.
5. `requirements.txt`, `config.example.yaml`, `.env.example`, and a **portfolio-grade README** with an **architecture diagram**, an explanation of hybrid retrieval + reranking + verification, and a **"how observability works here" section** (screenshots of traces, the metrics you track, and how prompt versions gate deploys).
6. A short **eval report** showing baseline metrics and an example of a caught regression.

## Acceptance criteria
- Ask a question over the sample corpus → get an answer with **verified** citations resolvable to source + location; insufficient context yields an honest "I don't have that," not a hallucination.
- Disabling reranking or switching fusion weights via config visibly changes retrieval — proving the pieces are real, not decorative.
- Running the eval harness prints retrieval + answer metrics vs. baseline.
- A deliberately bad prompt/config change makes the **CI gate fail**; a good one passes.
- Every query produces a **Langfuse trace** with per-stage spans, and the dashboard shows **p50/p95 latency, cost/request, citation coverage, and failure rate**.
- Each trace and eval run is attributable to a specific **prompt version**.

## Working style
- **First, propose the repo structure and library choices**, and once you can see the actual PDF, propose the chunking strategy and a handful of sample eval questions — confirm before building the full eval set.
- Build the **core pipeline end to end** before the eval/CI/observability layers — but do not treat those layers as optional; they are the graded part of this project.
- Assume CPU-only. Call out any step that's CPU-slow and how you kept it acceptable (small models, capped candidate counts).
- Be explicit about **cost**: which steps call the API, and how the eval loop avoids burning money on every push.

## Stretch (only after the above is solid)
- Query rewriting / HyDE before retrieval; contextual chunk headers; A/B comparison of two prompt versions in the eval harness; a small dashboard summarizing the observability metrics; automatic baseline updates on approved merges.
