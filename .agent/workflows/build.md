---
description: Execute an approved implementation plan using subagents and TDD.
---

# /build

Use this workflow to execute a structured implementation plan step-by-step.

## Core Principles
- **No Production Code Without a Failing Test**: The Iron Law of TDD.
- **Atomic Execution**: Complete one task, verify it, and commit it before moving on.
- **Systematic Verification**: Never assume it works because it "looks right".
- **Data First**: Verify data availability/structure before building the component that consumes it.

## The Process

1. **Setup**
   - Read the implementation plan from `docs/plans/`.
   - Ensure you are in the correct context (checkout branch if needed).

2. **Third-Party API Verification**
   - Before writing a RED test against a less-common third-party library API (config loaders, ORMs, CLI frameworks, index/vector-store libraries) — especially one the plan wrote example code for without running it — verify the actual behavior with a 5-line throwaway script first. Plan-time example code is a best guess, not a verified contract.
   - This session hit three real mismatches this way: `pydantic-settings`' `YamlConfigSettingsSource` doesn't support a per-instance `_yaml_file` init-kwarg override the way `_env_file` does (the plan's test design assumed it did); `typer` silently collapses to single-command mode — no subcommand name required — when only one `@app.command()` is registered, breaking a planned `runner.invoke(app, ["ingest", ...])` test shape until an empty `@app.callback()` forced multi-command mode; `python -m app.main` does not pick up `src/`-layout packages the way pytest's `pythonpath` ini option does — needs `PYTHONPATH` set explicitly for any manual (non-pytest) CLI invocation.
   - **Performance and behavior claims need production-shaped probe inputs.** A latency/throughput probe on toy inputs can "confirm" a design claim that is false for real data: the reranker probed at 63ms/16 pairs on short strings but runs ~5.3s/20 candidates on real 329-token-median chunks — an 80x gap the probe hid. The same applies to LLM instruction-following claims: one short live-API test passing does not confirm a prompt rule holds in general — Block 4's "cite only supporting chunks" rule looked correct on its first fixture, then a genuinely detailed question exceeded `max_tokens` and truncated the structured output entirely, and a separate off-topic-chunk case needed a second prompt fix before the citations rule actually held. When the claim under verification is about speed, size, or model behavior, probe with real corpus samples and a range of realistic input shapes, not one fixture-sized case.

3. **Contract & Isolation Checks**
   - A chunk's RED tests must include at least one *contract* case, not only planned behavior: parallel collections with mismatched lengths, empty inputs, and every signature parameter exercised by some assertion. Prefer APIs that fail loudly over ones that silently truncate (`zip(..., strict=True)`). Two consecutive audits found silent-contract bugs that happy-path TDD missed: a `min_tokens` parameter never referenced in the body, and RRF's `zip` silently dropping a whole ranking when the weights list was short.
   - **Config Isolation**: when adding a config key whose value is corpus-specific (page ranges, model names, paths), check which existing tests implicitly read the repo's `config.yaml` (it loads cwd-relative) and isolate them with a minimal-config fixture. Repo values poison synthetic fixtures — the corpus body-page-range filtered synthetic test PDFs down to zero chunks mid-build.
   - **Untested defenses are bugs waiting.** Do not add defensive code (limits, clamps, fallbacks) that no probe evidence demands and no RED test exercises — especially not against a threat a probe just showed doesn't exist. A `.limit(len(ids))` added as "cheap insurance" *after* the probe showed no default cap became itself the bug: duplicate rows inflated the match count past the limit and silently truncated the scan. Every defense gets its own RED test proving it defends, or it stays out. This applies even when the guard is provably *necessary*, not speculative: Block 4's `if ids else {}` short-circuit before a chunk-text lookup existed because an empty-list call genuinely crashes (confirmed by probe), but shipped with no test forcing that branch — a later refactor could delete it as "looks redundant" with nothing to say otherwise. A guard proven necessary by a probe still needs its own RED test asserting the failure it prevents doesn't happen, not just a test of the happy path around it.

4. **Debugging Protocol**
   - If a task fails more than once (same error or cycling through approaches), **stop and create a debug log** at `docs/debug-log-<topic>.md` with three columns: `Attempt | What was tried | Why it failed`.
   - Read this log before every subsequent attempt. This prevents Claude from re-trying approaches that already failed as context grows, and surfaces the actual constraint faster.
   - Delete the log once the task is resolved.

5. **Task Execution (Round-robin per task)**
   - For each task in the plan:
     - **RED**: Write the failing test as specified in the plan. Watch it fail.
     - **GREEN**: Write minimal code to make the test pass.
     - **REFACTOR**: Clean up code while keeping tests green.
     - **COMMIT**: Use the exact commit command from the plan.
6. **Subagent Handoff (Optional)**
   - If a task is complex, you may spawn a subagent to handle the RED-GREEN-REFACTOR cycle, but you MUST review its work against the plan's success criteria.

7. **Technical Debt Discovery**
   - As you implement, actively look for existing technical debt, complex code that needs refactoring, or missing edge case handling.
   - If found, and it's out of scope for the current task, IMMEDIATELY add it to `BUGS.md` or the appropriate technical debt tracker.
   - **Threshold Check**: Before writing a new instance of a pattern already flagged in `BUGS.md` with a "revisit if occurrence N appears" note (duplicated mock/fake scaffolding, a repeated config shape, etc.), check whether this new instance crosses that stated threshold. If it does, extract now instead of adding a fifth copy for a future audit to notice — Block 4 logged "revisit if a third fake-client test appears" and Block 6 shipped five more before anyone checked. This check isn't limited to patterns already logged in `BUGS.md` — also watch for a pattern repeating within the *same* session's own chunks (a hand-rolled test spy/fake copy-pasted into a second or third test file in this block). Block 7 hand-rolled the same `SpyTracer`/`_SpySpanCtx` fake independently across four test files and six tests within one build session, unnoticed until a dedicated `/audit` fresh-eyes pass — nothing during `/build` itself checks for intra-session duplication, only cross-session `BUGS.md` notes.

8. **Progress Tracking**
   - Check off tasks in the plan file as they are completed.
   - Update `PROJECT_HISTORY.md` at the end of the session.

**Next Step**: Once all tasks are complete, use **/audit** for the final quality and UX check.
