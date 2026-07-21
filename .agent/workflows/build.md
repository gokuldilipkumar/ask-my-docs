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
   - **This applies to UI/app testing harnesses too, not just config loaders and CLI frameworks** — the same "less-common third-party API" category includes things like `streamlit.testing.v1.AppTest`, React Testing Library, or any tool that drives a full app script/component rather than a plain function. Block 10's plan assumed `patch("app.streamlit_app.answer_with_verified_citations", ...)` (patching the name re-bound inside the script under test) would work — a real probe before writing the RED test found `AppTest` actually re-executes the whole script fresh on every `.run()` call, silently overwriting that patched name; the fix was to patch the *source* module the script imports from instead (`patch("citations.pipeline.answer_with_verified_citations", ...)`). Without the probe, this would have surfaced as a confusing RED-that-won't-go-GREEN during the actual chunk — a real API call appearing to fire despite being "mocked" — costing debugging time chasing the wrong layer instead of being resolved before the first real test was written.
   - **Performance and behavior claims need production-shaped probe inputs.** A latency/throughput probe on toy inputs can "confirm" a design claim that is false for real data: the reranker probed at 63ms/16 pairs on short strings but runs ~5.3s/20 candidates on real 329-token-median chunks — an 80x gap the probe hid. The same applies to LLM instruction-following claims: one short live-API test passing does not confirm a prompt rule holds in general — Block 4's "cite only supporting chunks" rule looked correct on its first fixture, then a genuinely detailed question exceeded `max_tokens` and truncated the structured output entirely, and a separate off-topic-chunk case needed a second prompt fix before the citations rule actually held. When the claim under verification is about speed, size, or model behavior, probe with real corpus samples and a range of realistic input shapes, not one fixture-sized case.
   - **A new or modified CI workflow (`.github/workflows/*.yml`) or other infra-as-code artifact is not done when the YAML looks right — it's done when it has actually run and been observed, once, in the real target environment.** Reading a workflow file cannot catch what only shows up at execution time: Block 8's `nightly-eval.yml` looked entirely correct on paper (right triggers, right secrets referenced, right steps) and still failed twice for a reason invisible in the YAML itself — an `httpx`/`h11` `LocalProtocolError` traced to a stray leading space in a `.env` value that a local parser tolerated but a raw `gh secret set` pipe didn't. Push it, watch it run (`gh run watch` / poll `gh run list`), read the actual log — don't mark an infra chunk complete on inspection alone.
   - **When piping a local config/secret value into a remote secret store (`gh secret set`, a cloud provider's CLI, etc.), never pipe raw file content directly — strip whitespace first (`xargs`, or equivalent).** Local config parsers (`pydantic-settings`' dotenv source, `python-dotenv`, most `.env` loaders) are commonly lenient about leading/trailing whitespace around a value; a raw shell pipe into a secret-store CLI is not, and preserves it byte-for-byte. The same nominal "API key value" silently behaved two different ways depending on which of `.env`'s two consumers read it — invisible until the byte-precise one (a GitHub Actions secret, then an HTTP header) rejected it three layers down the stack from where the actual data defect lived.
   - **A tracing/observability library's nesting behavior confirmed correct in isolation is not the same claim as the codebase actually producing nested output.** If a probe confirms "a child span opens under whatever parent context is currently active," that only tells you the *primitive* works — it does not tell you any real call chain in the codebase ever establishes that active parent context. Verify by checking whether each independent orchestrator that opens multiple leaf spans (retrieval, generation, verification, etc.) wraps its own call chain in one enclosing span — a shared client/tracer *instance* across leaf calls is necessary but not sufficient for nesting. Block 7 shipped 9 chunks and full unit-test coverage with every leaf function opening its own span correctly, but no orchestrator ever opened a wrapping span — invisible to every test because none exercised a real backend's actual nesting semantics, only span names/call counts on a fake. Caught only when a real trace was screenshotted for the first time, one block later.
   - **Before capturing real command output to embed in documentation (README, eval report, etc.), verify any local cache the command reads from was populated this session — or clear it.** A long-idle local cache can silently make "real, freshly-run" output represent a stale prior code/config state instead of current reality, while still looking like a legitimate real run (no error, plausible numbers). A local `eval` response cache last touched four days earlier returned 4-day-old judge verdicts with zero new API spend — caught only because the cost total suspiciously didn't move.
   - **When capturing multiple real command outputs into the same document, get each number from its own dedicated run immediately before using it — never reuse a figure captured earlier in the session for a different command.** A daily-cost total (or any other session-cumulative value) captured after one command is not the right value to paste next to a *different* command's output, even if both numbers look plausible; a UTC day rollover mid-session is what exposed one such mismatch here, but the same error would be invisible on a session that didn't happen to cross a day boundary.

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
