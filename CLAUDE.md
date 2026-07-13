# CLAUDE.md

**Ask My Docs** — production-shaped RAG over the FAA Airplane Flying Handbook (FAA-H-8083-3C): hybrid retrieval, rerank, cited generation, eval-gated CI, Langfuse observability. Full spec: `production-rag-build-prompt.md`. Portfolio piece (hiring-manager audience) — polish README/eval report accordingly.

**Stack**: Python 3.11+, CPU-only (no GPU), Anthropic API (sonnet=gen, haiku=judges), Windows dev / Linux CI.
**Non-goals**: local LLM, GPU, multi-tenant auth, fine-tuning.

## Lifecycle (`.agent/workflows/`)
`/brainstorm` design → `docs/plans/*-design.md` · `/plan` TDD task breakdown → `docs/plans/*.md` (skip the frontend/Supabase pre-flight steps — not applicable here) · `/build` RED-GREEN-REFACTOR · `/audit` verify spec compliance by running tests · `/kaizen` reduce entropy · `/log` track debt without starting work · `/closeout` kaizen → changelog → `PROJECT_HISTORY.md` → commit.

## Rules
- TDD is non-negotiable: no production code without a failing test first.
- Update `PROJECT_HISTORY.md` per session; decisions go in `.agent/decisions.log`; the *why/how* behind each session's work goes in `LEARNING_NOTES.md` (the user's primary learning artifact — never skip it at closeout).
- Atomic commits: `[Action] [Scope]: [Change]`.
- Config-driven, no magic numbers (chunk size, RRF weights, thresholds all in config).

## Skills (`skills/`)
`debugging`, `test-driven-development`, `kaizen`, `writing-skills` apply. `ui-development` does not (no frontend).
