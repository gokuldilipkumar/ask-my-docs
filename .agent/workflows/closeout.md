---
description: Wrap up a build/audit session -- learning notes, changelog, project history, commit.
---

# /closeout

Use this workflow to wrap up a development session once `/audit` has passed (or the user
has explicitly chosen a lighter closeout after a clean audit with nothing to fix).

## Prerequisites
- `/audit` has been run and its findings resolved (Blocking fixed, Improvements logged to
  `BUGS.md`, Nitpicks acknowledged) — or the user has explicitly said to skip straight to
  closeout after a clean result.

## The Process

### 1. `LEARNING_NOTES.md` (REQUIRED, never skip)
Append a dated entry. This is the user's primary learning artifact from the project — as
mandatory as `PROJECT_HISTORY.md`, and easy to silently skip since nothing else in the repo
enforces it.

Content: the *why* and *how it works* behind what was built or found this session — concept
explanations, failure patterns (the wrong assumption, the tell that exposed it, the fix's
reasoning), and rejected alternatives. Not a changelog rehash: `PROJECT_HISTORY.md` records
what happened; `LEARNING_NOTES.md` teaches why it mattered. Good sources: this session's
`/kaizen` friction points, audit findings, `.agent/decisions.log` entries, and any moment
where reality contradicted the plan or a library/model surprised us.

### 2. `CHANGELOG.md`
Add an entry for this session's shipped changes — user-facing/portfolio-relevant framing
(what changed, not the blow-by-blow of how it was built; that's `PROJECT_HISTORY.md`'s job).

### 3. `PROJECT_HISTORY.md`
Append a new row to the Session Log table (bottom of file, chronological — this project's
convention, not prepend-newest-first) with:
- **Date**
- **What I Did** — concrete, specific, names real files/commits/numbers where relevant
- **Key Decisions** — the load-bearing *why*, not a restatement of what
- **Next Steps** — what a future session should resume with, including any carried-forward
  open items from `BUGS.md`

### 4. `BUGS.md`
Confirm every item resolved this session is checked off (`~~strikethrough~~` + a dated
"Fixed" note, matching this file's existing convention) rather than left open by accident.
Items deliberately deferred stay open with an accurate note of why.

### 5. Plan Doc Checkboxes
If a `docs/plans/*.md` plan was built this session, confirm its Success Criteria checkboxes
are all checked (or explicitly marked as not applicable/deferred with a note) before moving
on — a plan doc that says "not yet built" after the work shipped is exactly the kind of
stale status marker `/audit`'s Documentation Freshness check looks for next time.

### 6. Git Hygiene
- **Test suite**: confirm `uv run pytest -q` is green (should already be true from
  `/audit`; re-run if any doc/config drift was fixed since).
- **Commit**: stage and commit the documentation updates with a clear
  `[Docs] Closeout: <scope> - history, learning notes, changelog` message (matches this
  project's atomic-commit convention, `.agent/decisions.log` for the *why*).
- **Push**: push to the remote (`gokuldilipkumar/ask-my-docs`) unless the user says not to.

### 7. Summary
Provide a concise final summary (5-8 bullets max): what shipped, what was deferred, test
count delta, and the next recommended step (`/plan` for the next block, or a specific
`BUGS.md` item worth addressing next).

## What this project does not have
No `PROJECT_ROADMAP.md`, no phase branches, no `npm`/lint/build steps, no
`/sync-workflows`, no CI-secret-hygiene step beyond what `/build`'s own CI chunks already
verify. Do not add these back in without the user asking for them.
