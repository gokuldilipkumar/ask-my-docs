# Eval Report — Ask My Docs

This report documents how retrieval and generation quality are measured for this RAG
system, the current real baseline numbers, and a real, reproducible example of the CI
quality gate catching a regression. Every number below comes directly from a committed
baseline file or a real command run against the real corpus — see the source noted next
to each figure.

## Methodology

Quality is measured against 8 golden questions (`eval/golden/questions.yaml`), each with
`relevant_chunk_ids` (retrieval ground truth) and `reference_notes` (an answer rubric for
the generation judge).

**Ground truth labeling.** Rather than hand-labeling every candidate chunk from scratch or
skipping ground truth entirely, relevance is LLM-labeled against a deliberately wide
candidate pool (`top_n=25`, wider than any rerank config's `top_k=5`), judged independently
of rank, then hand-reviewed and corrected by a human before being trusted
(`GoldenQuestion.reviewed`). A fully manual process would be more rigorous but all-manual
effort; deriving ground truth from the system's own ranking would risk circularity — the
system would be graded against its own opinion of what's relevant.

**Retrieval metrics** — `recall_at_k`, `mrr` (mean reciprocal rank), `ndcg` (normalized
discounted cumulative gain), computed over the reranked top-`k` results
(`eval.retrieval_k = 5`). Pure functions, no LLM involved — deterministic and free to run
on every push (`cheap-gate.yml`'s `--retrieval-only` mode).

**Generation metrics** — an independent LLM judge (`claude-haiku-4-5-20251001`, temperature
0.0) scores two boolean dimensions per answer: `correct` and `complete`. These are
deliberately independent rather than one combined score, because a real gap this project
found (Block 4's spot-check: a short-field/soft-field takeoff comparison question answered
only half the comparison) would not have been flagged by correctness alone — the answer
given was true, just incomplete. `correctness_rate`/`completeness_rate` are the fraction of
the 8 questions scored `True` on each dimension.

**Citation faithfulness** — `coverage`, from `citations.verify_citations`: the fraction of
a generated answer's citations that a second LLM pass confirms are actually supported by
their cited chunk. This is a real API call, not a heuristic, and runs only in the full
(non-`retrieval-only`) eval mode.

**CI gate** — `eval --retrieval-only` runs on every push (`cheap-gate.yml`), zero API cost.
The full judge-based run (`eval --save-baseline`) runs nightly (`nightly-eval.yml`) and
becomes the new tracked baseline. `compare_to_baseline` passes a metric if
`current >= baseline - tolerance` (`eval.tolerance = 0.1`) — a tolerance band, not a hard
cutoff, because generation is genuinely non-deterministic (see "What this harness has
already caught," below).

## Current Baseline Metrics

| Metric | 2026-07-14 (first baseline) | 2026-07-17 (current, CI-produced) |
|---|---|---|
| `mean_recall_at_k` | 0.616 | 0.616 |
| `mean_mrr` | 0.906 | 0.906 |
| `mean_ndcg` | 0.783 | 0.783 |
| `mean_coverage` | 1.000 | 1.000 |
| `correctness_rate` | 0.750 | 0.875 |
| `completeness_rate` | 0.500 | 0.625 |

Source: `eval/baselines/20260714T151052Z_dfac1522.json`, `eval/baselines/20260717T095425Z_3c6a14e9.json`.

Retrieval metrics are unchanged between the two baselines — nothing in retrieval/rerank
changed in that window. `correctness_rate` and `completeness_rate` improved
(0.75→0.875, 0.5→0.625), but this reflects real generation/judge variance between two
independent runs of the same corpus, config, and prompts, not a deliberate fix — see
`PROJECT_HISTORY.md`'s 2026-07-17 entry and the non-determinism finding below. The eval
harness's own tolerance-band design exists precisely because two honest runs of unchanged
code can legitimately differ this much.

## A Real, Reproducible Regression

To demonstrate the CI gate actually blocks a regression (not just theoretically could),
three real config changes were run against the real corpus via
`uv run python -m app.main eval --index data/index --retrieval-only`, each compared
against the current baseline above.

**Attempt 1 — `rerank.enabled: false`.** Expected: reranking should measurably help,
so disabling it should hurt. Actual result:

```
mean_recall_at_k: PASS (current=0.669, baseline=0.616)
mean_mrr:         PASS (current=0.906, baseline=0.906)
mean_ndcg:        PASS (current=0.830, baseline=0.783)
```

Every metric *improved*. Not the expected outcome — reported here rather than discarded,
because a demo that only shows the version of reality that confirms the premise isn't
evidence. For these 8 questions, cross-encoder reranking narrows RRF's fused top-`n` down
to `top_k=5`, but RRF's own fusion order already ranks relevant chunks competitively for
this candidate set; the reranker's precision gain doesn't show up in these particular
recall/mrr/ndcg numbers. This is a real, useful finding about this corpus/query set, not a
failure of the demo.

**Attempt 2 — `retrieval.top_n: 20 → 3`.** Shrinking the candidate pool that even reaches
reranking should mechanically hurt recall for questions with many relevant chunks (e.g.
`q6_upset_recovery` has 16 `relevant_chunk_ids`). Actual result:

```
mean_recall_at_k: PASS (current=0.537, baseline=0.616)
mean_mrr:         PASS (current=0.875, baseline=0.906)
mean_ndcg:        PASS (current=0.694, baseline=0.783)
```

All three metrics dropped in the expected direction, but stayed inside the 0.1 tolerance
band — the gate correctly does *not* block a change this small, matching its design intent
(don't fail CI on noise-level drift).

**Attempt 3 — `retrieval.top_n: 20 → 1`.** A more severe version of the same change:

```
mean_recall_at_k: FAIL (current=0.356, baseline=0.616)
mean_mrr:         PASS (current=0.875, baseline=0.906)
mean_ndcg:        FAIL (current=0.478, baseline=0.783)
```

Exit code: **1**. This is what `cheap-gate.yml` would report as a failed check on a real
pull request. Confirmed stable across two identical runs (retrieval-only mode makes no LLM
calls, so it's fully deterministic). `config.yaml` was reverted immediately after; a
follow-up run matched the control numbers above exactly, and `git diff config.yaml` showed
no net change.

This is the real evidence behind the "eval-gated CI" claim: not a hypothetical, a config
change that was actually run, actually failed, and would actually have blocked a real push.

## What This Harness Has Already Caught (in production, not staged)

Two real bugs surfaced by this eval harness during normal development, before any
portfolio-report demo was designed:

**Generation fabrication (Block 6, HIGH).** The very first real end-to-end eval run caught
question 4 ("common errors during a crosswind takeoff") fabricating an 8-item
"According to the handbook" errors list that does not exist anywhere in the corpus or in
the single chunk the answer cited. `citations.verify_citations` could not have caught this
— the cited chunk was genuinely relevant by its own per-citation definition; the fabrication
was in unverified prose, not an unsupported citation. This is exactly the scope boundary
citation verification was designed with (real chunk relevance vs. prose faithfulness), and
the answer-quality judge caught the failure mode citation verification was never meant to
cover.

**Generation non-determinism.** The same question (VMC vs. VSO) scored `correct=True` on
one real eval run and `correct=False` on an immediate re-run of the identical question,
with genuinely different generated text each time (`GenerationConfig` has no `temperature`
field — the Anthropic SDK's default applies). This is the concrete evidence behind the
tolerance-band (not hard-cutoff) design of `compare_to_baseline` used throughout this
report: a system that legitimately varies run-to-run cannot be gated with an exact-match
comparison without constant false-positive CI failures.

Neither of these was staged for this report — both are real findings from
`.agent/decisions.log` (2026-07-14) and `PROJECT_HISTORY.md`, included here as evidence the
harness does real work, not just computes numbers.

**A second, live instance, caught while writing this report.** Running the full
`eval --index data/index` command for this report's own quickstart capture produced a real
`correctness_rate`/`completeness_rate` gate FAIL — not staged, not expected:

```
correctness_rate:   FAIL (current=0.625, baseline=0.875)
completeness_rate:  FAIL (current=0.375, baseline=0.625)
```

Retrieval metrics (`recall_at_k`/`mrr`/`ndcg`/`coverage`) were all unchanged and PASS —
only the two LLM-judged dimensions moved, on the same 8 questions, same config, same
prompts as the current baseline. This is the same phenomenon as the VMC/VSO finding above,
observed a second time, live, days later, with zero code changes in between — direct
evidence that `nightly-eval.yml`'s judge-based gate is expected to show real variance
between runs, which is exactly why the cheap, deterministic `--retrieval-only` gate (not
this one) runs on every push, and the full judge-based gate runs nightly rather than
per-commit.
