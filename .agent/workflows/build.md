---
description: Execute an approved implementation plan using subagents and TDD.
---

# /build

Use this workflow to execute a structured implementation plan step-by-step.

## Core Principles
- **No Production Code Without a Failing Test**: The Iron Law of TDD.
- **Atomic Execution**: Complete one task, verify it, and commit it before moving on.
- **Systematic Verification**: Never assume it works because it "looks right".
- **Data First**: Verify data availability/structure before building the UI component that displays it.
- **P0 Standards**: Adhere to the checklists in **.agent/REFERENCE.md** during implementation.

## The Process

1. **Setup**
   - Read the implementation plan from `docs/plans/`.
   - Ensure you are in the correct context (checkout branch if needed).

2. **Third-Party API Verification**
   - Before writing a RED test against a less-common third-party library API (config loaders, ORMs, CLI frameworks, index/vector-store libraries) — especially one the plan wrote example code for without running it — verify the actual behavior with a 5-line throwaway script first. Plan-time example code is a best guess, not a verified contract.
   - This session hit three real mismatches this way: `pydantic-settings`' `YamlConfigSettingsSource` doesn't support a per-instance `_yaml_file` init-kwarg override the way `_env_file` does (the plan's test design assumed it did); `typer` silently collapses to single-command mode — no subcommand name required — when only one `@app.command()` is registered, breaking a planned `runner.invoke(app, ["ingest", ...])` test shape until an empty `@app.callback()` forced multi-command mode; `python -m app.main` does not pick up `src/`-layout packages the way pytest's `pythonpath` ini option does — needs `PYTHONPATH` set explicitly for any manual (non-pytest) CLI invocation.

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
   - **JSX Integration Check**: When inserting a new component into an existing page, ALWAYS `view_file` the full page first (not just the insertion point). Verify the JSX tree opens and closes correctly after your edit.
   - **UI Task Detection**:
     - When implementing UI components, auto-load `.interface-design/system.md` if exists
     - Apply craft principles from `ui-development` skill
     - Offer to save new patterns after completion

6. **Subagent Handoff (Optional)**
   - If a task is complex, you may spawn a subagent to handle the RED-GREEN-REFACTOR cycle, but you MUST review its work against the plan's success criteria.

7. **Technical Debt Discovery**
   - As you implement, actively look for existing technical debt, complex code that needs refactoring, or missing edge case handling.
   - If found, and it's out of scope for the current task, IMMEDIATELY add it to `BUGS.md` or the appropriate technical debt tracker.

8. **Progress Tracking**
   - Check off tasks in the plan file as they are completed.
   - Update `PROJECT_HISTORY.md` at the end of the session.

**Next Step**: Once all tasks are complete, use **/audit** for the final quality and UX check.
