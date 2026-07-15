---
description: Perform a combined technical and UX audit of newly built code.
---

# /audit

Use this workflow to ensure code is production-ready and aesthetically perfect before merging. This replaces separate code review and UX verification steps.

## 1. Technical Audit (The "Engine" Check)
Inspect the implementation for reliability and performance.
*   **Test Verification**: Run `uv run pytest -q` (full suite, slow tests included). If tests are missing or failing, the audit is **FAILED**.
*   **Fixture Parity**: If model/schema shapes changed this phase (e.g. `ingest.models`), verify shared conftest fixtures (`make_chunk`, `make_pdf`) and test stubs reflect the new shapes BEFORE running the suite, preventing cascading false failures.
*   **Index Integrity**: If `Chunk` fields or chunking behavior changed, both indexes (`bm25`, `lancedb`) must be rebuilt from a fresh ingest before any spot-check — stale indexes silently serve the old schema/corpus.
*   **Corpus Invariants**: When indexes were rebuilt (or index-reading code changed), verify the design doc's *stated* data invariants with actual counts, not assumption: total rows == unique `chunk_id` count in each index, and both indexes hold identical id sets. The duplicate-chunk-id bug (617 rows, 590 unique) sat undetected from Block 1 to Block 3 because "content-hash ids are unique" was designed, asserted nowhere, and counted never.
*   **Dead Code Check**: For every new public function or module this phase, verify it is imported somewhere other than its own file and its tests. If the only match is its own file, it is not wired in — treat as a finding.
*   **Composition Cost Check**: For any new code that composes an already-shipped pipeline function (e.g. `answer_question`, `answer_with_verified_citations`) alongside its own direct calls to that function's expensive upstream steps (retrieval, rerank, generation), verify the composed call isn't repeating a step already computed earlier in the same call path. Mocked tests hide this — the real cost only shows up against the real corpus. Block 6's `_evaluate_one` retrieved+reranked directly for metrics, then called `answer_with_verified_citations`, which retrieved+reranked again internally at ~5.3s/query real cost.
*   **Guard Coverage**: For every conditional short-circuit or early-return added or changed this phase, verify a test forces that branch and exercises the failure it exists to prevent — not just that the happy path still passes. Block 4's `answer_question` short-circuited on empty retrieval to avoid a real crash (`get_chunk_texts([])` raises an opaque LanceDB SQL-parser error), but shipped with no test proving the guard fires; found only by manually reasoning through the branch during audit, not by any checklist item.
*   **Config Template Sync**: If `config.yaml` or a `*Config` class in `settings.py` changed this phase, diff `config.example.yaml`'s matching section against it. The example template is read by no test and by nothing in `Settings` — Block 4 changed `generation.model`, added `max_tokens`/`timeout_seconds`, and dropped `backoff_base_seconds` in `config.yaml`, and `config.example.yaml` sat on the old shape until a fresh-eyes review caught it.
*   **Contract Check**: For every new/changed function signature, verify (a) each parameter is referenced in the body, and (b) parallel-collection inputs fail loudly on length mismatch (`zip(..., strict=True)`), never silently truncate. Both bug classes shipped past happy-path TDD here: a dead `min_tokens` parameter, and RRF's `zip` silently dropping a whole ranking.
*   **Comment Integrity**: For comments added or changed this phase that state factual or quantitative claims ("X is an upper bound", "Y gates Z"), verify each claim against the code. A false comment shipped inside a previous audit's own fix and survived a full audit cycle.
*   **CLI Entry Points**: Any manual (non-pytest) CLI invocation needs `PYTHONPATH=src` — `python -m app.main` does not pick up the src-layout the way pytest's `pythonpath` ini option does.

### Clean Code (Entropy Review)
Spawn a fresh subagent with **only** the changed files as context — no plan doc, no conversation history, no justification. Use `git diff --name-only HEAD~N` to identify files modified this phase. Give the subagent this prompt:

> "Review these files as a senior engineer seeing them for the first time. Identify: (1) code that solves a problem that doesn't exist yet (YAGNI), (2) duplicated logic that should be a shared utility (DRY), (3) abstractions introduced for a single use case (premature abstraction), (4) functions or components doing more than one job (single responsibility), (5) anything that will be confusing to the next person reading this. Be specific — name the file and line. Do not praise what's working."

Triage findings into three buckets:

| Bucket | Definition | Action | Symptom Patterns |
|---|---|---|---|
| **Blocking** | Violates DRY, YAGNI, or SRP in a way that will cause real future pain | Fix before proceeding | "code that solves a problem that doesn't exist yet" / "duplicated 3+ times" / "doing more than one job" / logic should be extracted |
| **Improvement** | Valid point, non-urgent | Log to `BUGS.md` as Low DEBT | "undocumented", "should be", "fragile", "magic number without comment", "inconsistent with existing pattern" |
| **Nitpick** | Style, naming preference, minor | Acknowledge, skip | "why", "next person will wonder", "naming inconsistency", "could use shorter name", "comment might help" |

Fix all Blocking issues and re-run tests. If blocking issues were fixed, re-run the subagent on the updated files until its highest-severity finding is Improvement or lower. Note: the subagent will sometimes critique intentional simplicity as "missing abstraction" — the right amount of complexity is the minimum needed for the current task.

## 2. Documentation & Corpus Audit (The "Chassis" Check)
No frontend exists — verify the artifacts a hiring manager will read, and the retrieval behavior itself.
*   **Documentation Freshness**: Search for stale status markers (`ready to build|in progress|pending|not yet built`) in `docs/plans/*.md`, `BUGS.md`, `PROJECT_HISTORY.md` — use the harness Grep tool, not `bash -c "grep ..."` from PowerShell (plain `bash` resolves to WSL on this machine, which has no distro installed). Cross-check against git history. If a phase shows as pending but its commits exist, update the status.
*   **Real-Corpus Spot-Check**: If ingestion or retrieval code changed this phase, re-run the spot-check queries against the real handbook indexes and compare with the previous session's findings. Synthetic-fixture tests cannot catch corpus-level regressions (fragmented headers, polluted top-5s).
*   **Portfolio Quality**: Any README / eval report / architecture doc touched this phase must read presentation-quality (CLAUDE.md's hiring-manager audience).

## 3. Results & Remediation
*   **Small Fixes**: Correct minor typos, spacing, or color variables immediately.
*   **Blocking Issues**: Add any bugs or UX debt to `BUGS.md` with `/log`. For debt items that involve moving code, use this template for maximum agent-fixability:
    ```
    Move X from file A (line N) to file B. Update imports in: file C, file D.
    ```
    Include: what moves, exact source location, destination, and every affected import site. An agent given this template can execute the fix without any investigation step.
*   **Audit Status**:
    *   ✅ **PASS**: Specs met, suite green, docs/corpus checks verified.
    *   ❌ **FAIL**: Known bugs, failing tests, or stale docs left uncorrected.

**Next Step**: Once audit is passing, run `/kaizen` followed by `/closeout`.
