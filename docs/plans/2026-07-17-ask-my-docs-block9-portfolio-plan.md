# Block 9 Implementation Plan — Portfolio Deliverables

**Date**: 2026-07-17
**Parent plan**: `2026-07-11-ask-my-docs-implementation-plan.md` (Block 9 sketch)
**Design doc**: `2026-07-10-ask-my-docs-design.md`

## Header

- **Goal**: Produce the three portfolio deliverables the design doc names for a hiring-manager audience — a README with an architecture diagram and an explained rationale for hybrid retrieval/reranking/citation verification, an observability section backed by a real Langfuse trace screenshot, and an eval report showing the real baseline metrics plus one real, reproducible caught-regression example.
- **Architecture**: Everything in this block is documentation plus one small piece of real, run-and-observed evidence gathering — no new `src/` modules. Three artifacts: `README.md` (repo root, GitHub's default landing page), `docs/eval-report.md` (baseline metrics table + regression narrative), `docs/images/langfuse-trace.png` (real trace screenshot, referenced from the README). The architecture diagram is a `mermaid` block embedded directly in `README.md` (renders natively on GitHub, no image-generation tooling needed).
- **Design patterns**: N/A (no code). The organizing principle instead: every factual claim in these documents must be independently verified against something real before it's written down — a real command run, a real stored baseline JSON, a real screenshot — not asserted from memory of what the code is supposed to do. This project's own audit history is the reason: the stale `config.example.yaml` (Block 4 audit) and the placeholder price table (Block 7, still open) are both cases of unverified documentation/config drifting from reality. Portfolio docs are the highest-visibility place for that failure mode to recur.
- **Tech stack**: No new dependencies. GitHub-native Mermaid rendering for the architecture diagram; a real Langfuse Cloud free-tier project (user-provisioned) for the trace screenshot.

## Conventions Check (per `/plan` workflow, adapted per `CLAUDE.md` — no frontend/Supabase steps apply)

- **Reuse audit**: No README exists yet (confirmed: `ls README.md` → not found). `docs/eval-report.md` does not exist. Two real eval baselines already exist and require no new eval code: `eval/baselines/20260714T151052Z_dfac1522.json` (first real baseline, `correctness_rate=0.75`, `completeness_rate=0.5`) and `eval/baselines/20260717T095425Z_3c6a14e9.json` (current, CI-produced, `correctness_rate=0.875`, `completeness_rate=0.625`). The `eval` CLI command (`src/app/main.py:64-102`) already prints a per-metric PASS/FAIL table against the latest baseline — the regression demo (Chunk 9.1) captures its real stdout rather than hand-authoring a table. `Chunk 7.10` (real Langfuse trace verification) was fully speced in `docs/plans/2026-07-15-ask-my-docs-block7-observability-plan.md:815-843` and never built (blocked on empty credentials) — Chunk 9.0 below resumes it verbatim rather than re-designing it.
- **Composition Cost Audit**: Chunk 9.1's regression demo must not make new real Anthropic API calls beyond what's already been spent. Disabling `rerank.enabled` and re-running `eval --retrieval-only` computes only `recall_at_k`/`mrr`/`ndcg` locally (BM25 + the local cross-encoder/embedding models) — zero API cost, confirmed by Block 8's `retrieval_only` design (`compare_to_baseline` skips `None`-valued answer-quality fields, so a retrieval-only run compares cleanly against the existing full-run baseline with no new baseline store needed). No `judge_answer`/`generate_answer`/`verify_citations` calls happen in this chunk.
- **Additive-Parameter Reach Audit**: N/A — no function signatures change in this block.
- **Test style**: N/A for the doc chunks. Chunk 9.0 resumes real code from Block 7's plan (the `live_langfuse`-gated test) — same `pytest` conventions as the rest of the suite, gated behind `RUN_LIVE_LANGFUSE_TESTS=1` exactly like `live_api`'s `RUN_LIVE_API_TESTS=1`.
- **Config-isolation check**: Chunk 9.1 edits `config.yaml` (`rerank.enabled: false`) to produce the regression, then reverts it in the same chunk before committing — the repo's tracked `config.yaml` must end this block identical to how it started (`rerank.enabled: true`), verified by `git diff config.yaml` showing no net change before the final commit.
- **Verified-claim requirement** (this block's equivalent of the Heuristic Extraction Sampling check, since there's no extraction logic here): every numeric claim, command, and code snippet placed in `README.md` or `docs/eval-report.md` must be checked against a real source before being written — either by running the command and capturing real output, or by reading the real value from a committed file (baseline JSON, `config.yaml`, `pyproject.toml`). No hand-typed "illustrative" numbers or command output.

### Decisions made at plan time (not deferred to build)

1. **The user provisions a free Langfuse Cloud project this session and populates real `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` in `.env`**, unblocking Chunk 7.10 as this block's first chunk (9.0), rather than documenting the observability architecture without a real trace. User's explicit choice — the design doc's acceptance criterion ("dashboard shows p50/p95 latency, cost/request, citation coverage, failure rate") is otherwise undemonstrated for the entire project. Per the established `.env`-whitespace lesson (Block 8), keys are written with the same strip-before-write care used for `ANTHROPIC_API_KEY`.
2. **The eval report's "caught regression" example is a real, freshly-run intentional regression** (`rerank.enabled: false`, `eval --retrieval-only` against the real corpus and real committed baseline), not a reused historical bug narrative or the existing unit-test fixture from Chunk 8.3. User's explicit choice — a live before/after run against the real stored baseline is stronger portfolio evidence than citing a fixture or a past incident, and costs nothing extra (retrieval-only, no API calls per the Composition Cost Audit above). The already-logged HIGH q4 fabrication bug and the `mrr` vacuous-truth fix remain available as supplementary "what this harness already caught in production" narrative color inside the same report — not the headline example, since neither is reproducible on demand the way a deliberate config regression is.
3. **The architecture diagram lives inline in `README.md` as a Mermaid block**, not a separately generated/hosted image. GitHub renders Mermaid natively in `.md` files; no image-export tooling, no broken-link risk if the repo moves, and the diagram source stays diffable in code review — consistent with this project's preference for config/text over generated binary artifacts wherever equivalent (e.g. `config.yaml` over hardcoded values).
4. **The eval report is a separate file (`docs/eval-report.md`), linked from the README, not inlined into the README body.** The README's job is orientation for a first-time reader (what is this, why, how do I run it); the eval report's job is evidence (numbers, methodology, one regression walkthrough) for a reader who wants to verify the quality claims. Keeping them separate lets each stay focused — matches the design doc's own listing of them as two distinct deliverables.

## Block 9: Portfolio Deliverables

**Success criteria**

- [x] A real Langfuse Cloud trace exists for a real query against the real corpus, screenshotted and embedded in the README's observability section; `tests/observability/test_live_trace.py` (Block 7's deferred Chunk 7.10) passes with `RUN_LIVE_LANGFUSE_TESTS=1`. **Found and fixed a real HIGH bug along the way** (not in the original plan): spans were never actually nesting into one trace — see `BUGS.md`/`.agent/decisions.log` 2026-07-17. Screenshot: `docs/images/langfuse-trace.png`, one `query.answer_with_verified_citations` trace with all 6 spans nested correctly.
- [x] A real, reproducible regression run shows a measured drop in `recall_at_k`/`mrr`/`ndcg` vs. the real committed baseline, captured via the actual `eval --retrieval-only` CLI output (including its PASS/FAIL gate table), with `config.yaml` reverted afterward. **The planned regression (`rerank.enabled: false`) didn't reproduce** — it measurably *improved* every retrieval metric (recall 0.616→0.669, ndcg 0.783→0.830), all PASS; a real, honest finding, not the expected result. `retrieval.top_n: 20 → 3` degraded all three metrics but stayed within the 0.1 tolerance band (still PASS). `retrieval.top_n: 20 → 1` produced a real gate failure: `mean_recall_at_k` 0.616→0.356 (FAIL), `mean_ndcg` 0.783→0.478 (FAIL), `mean_mrr` 0.906→0.875 (PASS), exit code 1 — confirmed stable across two identical runs (retrieval-only mode is deterministic, no LLM). Reverted; `git diff config.yaml` clean; re-run matched control exactly.
- [x] `docs/eval-report.md` exists: baseline metrics table (both stored baselines), the regression example with real before/after numbers and real CLI output, and a short "what this harness has already caught" section referencing the real q4 fabrication bug and generation non-determinism finding from project history.
- [x] `README.md` exists at repo root: project pitch/audience framing, a Mermaid architecture diagram matching the real pipeline (verified against real span names and real module call chains, confirmed rendering on the real pushed GitHub page), an explained rationale for hybrid retrieval + RRF fusion + reranking + citation verification (the *why*, not just the *what*), a quickstart section where every shown command was actually run and its real output captured, an observability section with the real trace screenshot (confirmed displaying on the real pushed page), a link to `docs/eval-report.md`, and CI status badges for both workflows (both verified HTTP 200).
- [x] Every command shown in `README.md` was actually executed this session against the real repo state and its output verified to match what's documented (no hand-typed illustrative output). Caught and fixed one real drift: the `--retrieval-only` quickstart block initially showed a cost figure copy-pasted from a different command's output; corrected after noticing a UTC day rollover mid-session made the mismatch detectable, re-verified with a fresh run.
- [x] `git diff config.yaml` shows no net change after this block (the regression chunk's edit is fully reverted). Confirmed clean at final polish pass (Chunk 9.5).

---

### Chunk 9.0 — Langfuse Cloud setup + real trace verification (resumes Block 7's blocked Chunk 7.10)

**Files**: Modify `tests/conftest.py` (register `live_langfuse` marker, mirrors the existing `live_api` gate); Create `tests/observability/test_live_trace.py` (exact content already speced in `docs/plans/2026-07-15-ask-my-docs-block7-observability-plan.md:821-843`); Modify `.env` (real `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, whitespace-stripped); Create `docs/images/langfuse-trace.png`.

**Step 1 — prerequisite**: user creates a free Langfuse Cloud project at `cloud.langfuse.com`, generates an API key pair, provides both keys. Write them into `.env` stripped of surrounding whitespace (same `xargs`-based approach that fixed the `ANTHROPIC_API_KEY` byte-literal bug in Block 8) — verify with a byte-level check (`xxd` or equivalent) that no leading/trailing whitespace made it into the file, not just a visual read.

**Step 2 — register the marker and add the test**: add `"live_langfuse: hits a real Langfuse Cloud project, skip by default, run with RUN_LIVE_LANGFUSE_TESTS=1"` to `pyproject.toml`'s `markers` list and to `tests/conftest.py`'s skip-gate (mirroring `live_api`'s existing pattern exactly — read `tests/conftest.py` first to match its structure precisely). Add `tests/observability/test_live_trace.py` with the test from the Block 7 plan.

**Step 3 — run for real**: `RUN_LIVE_LANGFUSE_TESTS=1 uv run pytest tests/observability/test_live_trace.py -v -m live_langfuse` → real query against the real corpus, real trace sent to Langfuse Cloud.

**Step 4 — verify and capture**: open the Langfuse Cloud dashboard, confirm one trace with nested `retrieval.bm25.search` / `retrieval.vector.search` / `retrieval.fusion.rrf` / `rerank.score` / `generate.answer` / `citations.verify` spans, usage/cost visible on the two generation-type spans (matches the design doc's own diagram, Chunk 9.4 will cross-check the diagram against this real structure). Screenshot the full nested trace view, save as `docs/images/langfuse-trace.png`.

**Step 5 — commit**: `git add tests/conftest.py tests/observability/test_live_trace.py pyproject.toml docs/images/langfuse-trace.png && git commit -m "[Feature] Observability: real Langfuse Cloud trace verification (Chunk 7.10, unblocked)"` — `.env` is gitignored, not committed.

---

### Chunk 9.1 — real intentional regression run (rerank disabled)

**Files**: Modify `config.yaml` (temporarily); no test files — this is a real-corpus operational run, not a code change.

**Step 1 — capture the current-state control run**: `uv run python -m app.main eval --index data/index --retrieval-only` against the unmodified `config.yaml` (`rerank.enabled: true`). Capture the real stdout verbatim (per-metric PASS/FAIL lines + `mean_recall_at_k`/`mean_mrr`/`mean_ndcg` values) — this must exactly match `eval/baselines/20260717T095425Z_3c6a14e9.json`'s retrieval fields, confirming the control run is a true no-op before introducing the regression.

**Step 2 — introduce the regression**: edit `config.yaml`, set `rerank.enabled: false`. Run `uv run python -m app.main eval --index data/index --retrieval-only` again. Capture the real stdout — expect measurable drops in `mean_recall_at_k`/`mean_mrr`/`mean_ndcg` vs. the baseline (Block 3's spot-check already established reranking changes top-5 results on real queries; this is the first time that's measured quantitatively rather than eyeballed) and at least one metric's PASS/FAIL flipping to FAIL, demonstrating the CI gate would actually block this change (`exit_code=1` — confirm via `echo $?` / `$LASTEXITCODE`).

**Step 3 — verify the numbers are real, not fabricated**: re-run once more to confirm the regressed numbers are stable (deterministic — no LLM involved in `retrieval_only` mode, unlike the generation non-determinism found in Block 6). If retrieval is itself non-deterministic for any reason, note that explicitly rather than silently picking the more dramatic of two runs.

**Step 4 — revert**: set `config.yaml`'s `rerank.enabled` back to `true`. `git diff config.yaml` must show no changes. Re-run `eval --retrieval-only` one final time to confirm it matches the Step 1 control numbers exactly, proving the revert is clean.

**Step 5 — no commit** (no net code change — `config.yaml` ends identical to how it started). Both captured stdout blocks (control + regressed) carry forward into Chunk 9.2 as real evidence, not this chunk's own artifact.

---

### Chunk 9.2 — `docs/eval-report.md`

**Files**: Create `docs/eval-report.md`.

**Step 1 — assemble real data**: pull the metrics table directly from both baseline JSON files (`eval/baselines/20260714T151052Z_dfac1522.json`, `eval/baselines/20260717T095425Z_3c6a14e9.json`) — real numbers, not retyped from memory. Pull the regression before/after numbers and real CLI output from Chunk 9.1.

**Step 2 — write the report**: sections — (1) methodology (8 golden questions, LLM-labeled-then-human-reviewed ground truth, Recall@k/MRR/nDCG for retrieval, correct/complete booleans via an independent LLM judge for generation, `verify_citations`' coverage for citation faithfulness — cite `.agent/decisions.log`'s 2026-07-14 entries for *why* each metric choice was made, not just what it is); (2) current baseline metrics table (both stored baselines, showing the real `correctness_rate` 0.75→0.875 / `completeness_rate` 0.5→0.625 improvement between them, framed accurately as observed generation/judge variance per the 2026-07-17 `PROJECT_HISTORY.md` entry, not claimed as a deliberate fix); (3) the regression walkthrough from Chunk 9.1 — the exact config change, the real before/after numbers, the real gate output showing FAIL, framed as "this is what the CI gate catches on every push"; (4) a short "what this harness has already caught in production" section citing the real q4 generation-fabrication bug (Block 6, `.agent/decisions.log` 2026-07-14) and the `mrr` vacuous-truth fix (same session) as genuine examples of the eval harness surfacing real bugs, not hypothetical value.

**Step 3 — verify**: every number in the report traced back to its source file/command output from Steps 1 and cross-checked one more time by re-opening the source JSON/log rather than trusting the draft.

**Step 4 — n/a** (no pass/fail check for prose — Step 3's cross-check is this chunk's verification).

**Step 5 — commit**: `git add docs/eval-report.md && git commit -m "[Docs] Eval report: baseline metrics, real regression example, caught-bug narrative"`

---

### Chunk 9.3 — architecture diagram (Mermaid, verified against real code)

**Files**: no standalone file — diagram is authored here, embedded into `README.md` in Chunk 9.4.

**Step 1 — draft against real structure**: build the Mermaid flowchart from the real call chain, not the design doc's original sketch — read `src/citations/pipeline.py` (`answer_with_verified_citations`) and `src/generate/pipeline.py` (`answer_question`) to confirm the real order: query → `hybrid_retrieve` (three spans: `retrieval.bm25.search`, `retrieval.vector.search`, `retrieval.fusion.rrf`, per `src/retrieval/hybrid.py`) → `rerank` (`rerank.score` span, `src/rerank/cross_encoder.py`) → `generate_answer` (`generate.answer` span, `src/generate/client.py`) → `verify_citations` (`citations.verify` span, `src/citations/verify.py`) → verified answer. Cross-check span names against Chunk 9.0's real captured trace, not just the source code, so the diagram matches what a reader would actually see in the screenshot next to it.

**Step 2 — verify it renders**: paste the Mermaid block into a scratch `.md` file and preview it (or check via a GitHub Gist/PR preview) before committing to `README.md` — a syntax error in Mermaid fails silently as plain text on GitHub, easy to miss.

**Step 3-5**: folded into Chunk 9.4's commit (diagram is embedded directly in `README.md`, not a separate file).

---

### Chunk 9.4 — `README.md`

**Files**: Create `README.md`.

**Step 1 — gather real command output**: run the real quickstart commands against the real repo state and capture actual output —
- `uv sync` (dependency install)
- `uv run python -m app.main ingest --pdf "Airplane Flying Handbook (FAA-H-8083-3C).pdf" --out data/index` (or note the committed index means this step is optional for a reader — check real behavior, don't assume)
- `uv run python -m app.main query --question "What's the difference between VMC and VSO?"` — capture the real answer, citations, coverage, and daily-cost lines exactly as printed
- `uv run python -m app.main eval --index data/index` — real PASS/FAIL table
- `uv run pytest -m "not slow"` — real pass count

**Step 2 — write the README**: sections — project pitch (portfolio framing per `CLAUDE.md`'s audience note — what problem this solves, referencing `PROJECT_HISTORY.md`'s "Core Philosophy" section's own framing of *why* eval-gated RAG matters, not generic RAG boilerplate); Chunk 9.3's Mermaid architecture diagram; an explained rationale section (hybrid retrieval = lexical + semantic complementary strengths, RRF fusion = rank-based combination robust to differing score scales, reranking = precision correction on a cheap recall-heavy candidate set, citation verification = catches unsupported claims *and* is explicitly scoped to not catch prose fabrication — link to `docs/eval-report.md`'s q4 example as the concrete evidence for that scope boundary); quickstart with Step 1's real captured output; observability section with Chunk 9.0's real trace screenshot and a short explanation of the cost/budget-cap mechanism; a link to `docs/eval-report.md`; CI status badges (`https://github.com/gokuldilipkumar/ask-my-docs/actions/workflows/cheap-gate.yml/badge.svg` and the `nightly-eval.yml` equivalent — verify both badge URLs actually resolve to a real workflow status, not a 404).

**Step 3 — verify every command block**: re-run each shown command fresh (not from Step 1's cache) and diff against what's written in the README — catches any drift between the capture pass and the final draft.

**Step 4 — verify diagram + badges render**: view the committed `README.md` on GitHub's actual repo page after pushing (not just a local preview) — Mermaid rendering and badge image loading are both GitHub-server-side behaviors that a local Markdown preview can't fully confirm.

**Step 5 — commit**: `git add README.md && git commit -m "[Docs] README: architecture diagram, quickstart, observability, eval report link"`

---

### Chunk 9.5 — final polish pass

**Files**: Potentially modify `README.md`, `docs/eval-report.md` if Step 1 finds drift.

**Step 1 — link and command audit**: click/verify every link in both documents (internal doc links, CI badge URLs, image paths); re-run every command block one final time against the pushed state (not local working tree) by checking out a clean clone if feasible, or at minimum confirming `git status` is clean and nothing shown depends on uncommitted local state.

**Step 2 — cross-document consistency check**: confirm the metrics quoted in `README.md`'s observability/eval sections match `docs/eval-report.md` exactly (same source baseline files, no transcription drift between the two documents).

**Step 3 — fix any drift found**, re-verify.

**Step 4 — n/a**.

**Step 5 — commit** (only if Step 1-3 found and fixed something): `git add README.md docs/eval-report.md && git commit -m "[Docs] Fix drift found in final portfolio-docs polish pass"`

## Technical Debt Strategy

- **Chunk 9.0's Langfuse trace is a single real query, not a representative sample.** Acceptable for portfolio evidence (the design doc's stated goal is "every query produces a traced span," which the code already guarantees structurally per Block 7 — this chunk exists to *prove* the guarantee once with real infrastructure, not to characterize typical trace shapes across many queries).
- **The price-table placeholder verification (open since Block 7) is not addressed by this block.** If the eval report's cost figures are ever added (not currently planned — the report focuses on quality metrics, not cost), this would need resolving first. Logged already in `BUGS.md`; not re-logged here.
- **The HIGH q4 fabrication bug and `generation.temperature` non-determinism remain open**, referenced narratively in `docs/eval-report.md` as evidence the harness works, but not fixed by this block — Block 9 is documentation, not a bugfix block. If the user wants the portfolio's own quality bar to reflect a fixed q4, that's a pre-Block-9 detour, not part of this plan as written.

## Persistence & Next Step

Saved to `docs/plans/2026-07-17-ask-my-docs-block9-portfolio-plan.md`.

**Ready to start building? Use `/build`.**
