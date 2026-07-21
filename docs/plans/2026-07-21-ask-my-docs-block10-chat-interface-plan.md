# Block 10 Implementation Plan — Chat Interface

**Date**: 2026-07-21
**Parent plan**: `2026-07-11-ask-my-docs-implementation-plan.md` — no sketch exists for this block; a `serve` CLI command was contemplated and explicitly deferred at Block 8 (`.agent/decisions.log`, 2026-07-16: "skip the stretch-goal `serve` CLI command this block... a long-running server has its own framework/auth/deployment questions better scoped separately"). This block is that deferred question, scoped now as a standalone addition after the original 9-block plan (design → Block 9) already closed.
**Design doc**: `2026-07-10-ask-my-docs-design.md` (no UI section — this block is new scope, not a design-doc acceptance criterion)

## Header

- **Goal**: A Streamlit chat UI over the existing `answer_with_verified_citations` pipeline — question in, cited answer out, human-readable sources (not raw chunk-id hashes), a low-confidence flag, and a running daily-cost display — reusing 100% of the already-built retrieval/rerank/generation/citation-verification pipeline with zero changes to its internals.
- **Architecture**: Three additive pieces, no changes to any existing tuned/audited pipeline code:
  1. A new `data/index/chunk_metadata.json` sidecar produced at ingest time, resolving `chunk_id → {chapter_number, chapter_title, section_title, printed_page_label}` — this is what turns `["abc123"]` into `"Ch. 4: Energy Management — Total Energy"` and closes the open `BUGS.md` item under CLI/CI ("`query`'s citation display prints raw `chunk_id`s... Block 9 territory" — actually landed here, one block later).
  2. `src/app/streamlit_app.py` — a thin presentation layer. Same shape as `src/app/main.py`: imports pipeline functions directly, no new business-logic module in between.
  3. `streamlit.testing.v1.AppTest` for TDD coverage of the script itself (Streamlit ships an official headless test harness — exact mocking mechanics get verified with a real probe in Chunk 10.0 before any RED test is written against it, per this project's own `build.md` rule).
- **Design patterns**: N/A beyond what's already established (thin CLI/UI layer over pipeline functions, Settings-driven config). No new abstraction layer — a bug fix or a UI doesn't need one per this project's own economy-of-abstraction practice (see `BUGS.md`'s repeated "wait for a third occurrence" notes).
- **Tech stack**: `streamlit` (new main dependency — the shipped app needs it at runtime, not just for dev/test, so it goes in `[project.dependencies]`, not `dev`). No other new dependencies; reuses `anthropic`, `pydantic-settings`, existing pipeline.

## Conventions Check (per `/plan` workflow, adapted per `CLAUDE.md` — no frontend/Supabase steps apply)

- **Reuse audit**: `answer_with_verified_citations` (`src/citations/pipeline.py:12`) already does retrieval + rerank + generation + citation verification in one call — the UI must call this and only this, never re-implement or duplicate a step of it. `get_daily_total` (`src/observability/daily_cost.py`) and `check_budget` (same file, already imported by `src/observability/usage.py:6` but not yet by any CLI/UI surface) cover cost display. `get_chunk_texts` (`src/ingest/vector_index.py:41`) is *not* reused for citation display — it returns chunk body text for the citation-verification judge prompt, not display metadata; confirmed by reading the file that neither the BM25 index (`src/ingest/bm25_index.py`) nor the LanceDB table schema (`src/ingest/vector_index.py:24-34`, columns are only `chunk_id`/`text`/`vector`) persist `chapter_number`/`chapter_title`/`section_title`/`printed_page_label` anywhere post-ingest, even though the in-memory `Chunk` model (`src/ingest/models.py:31-42`) carries all of it. No existing function resolves chunk-id → human-readable citation — confirmed via `grep -rn "chapter_title" src/` returning only `src/ingest/`. New code needed for Chunk 10.1.
- **Composition Cost Audit**: the Streamlit app calls `answer_with_verified_citations` exactly once per submitted question — the same single real retrieval+rerank+generation+verification pass the CLI's `query` command already makes, no duplicate expensive step. `get_daily_total`/`check_budget` are cheap local SQLite reads, safe to call on every rerun (Streamlit reruns the whole script on each interaction) without adding a real API cost.
- **Additive-Parameter Reach Audit**: no existing function signature changes. `write_chunk_metadata` is a brand-new function called from exactly one place (`ingest` command in `src/app/main.py`); no existing caller needs updating.
- **Predicted-Behavior Claim Check**: Chunk 10.0's premise — that `streamlit.testing.v1.AppTest` supports mocking the pipeline call before `.run()` — is an unverified empirical claim about a third-party API, not a design fact. It gets a real probe (a throwaway two-line dummy script + `AppTest.from_file(...)`) before any RED test is written against the assumed mechanism, exactly matching this project's own `build.md` rule ("verify third-party API behavior with a real probe before shipping") — three prior blocks (`pydantic-settings` YAML source, `typer`'s single-command collapse, `PYTHONPATH` not propagating outside pytest) were each caught this same way and are documented in `LEARNING_NOTES.md`.
- **Test style**: `pytest`, `CliRunner` for the CLI-side `chunk_metadata` wiring (matches `tests/app/test_ingest_command.py`), `AppTest` for the Streamlit script (new to this project — pattern confirmed in Chunk 10.0). Existing `make_chunk` conftest fixture (`tests/conftest.py:27-41`) covers the metadata round-trip tests; no new shared fixture needed unless Chunk 10.0's probe says otherwise.
- **Runtime-path gotcha carried forward**: `PYTHONPATH=src` is required for any manual (non-pytest) invocation — documented in `.agent/workflows/audit.md:23`, `LEARNING_NOTES.md:97/113/233-234`, and both CI workflows. `streamlit run src/app/streamlit_app.py` is a manual invocation exactly like `python -m app.main` — it needs `PYTHONPATH=src` set explicitly too, or its internal `from citations.pipeline import ...` will fail with `ModuleNotFoundError`. Verified as a real constraint, not assumed, in Chunk 10.0.
- **Config-driven, no magic numbers**: no new tunable numeric parameters are introduced by this block (no new chunk sizes, thresholds, or weights) — the UI reuses `Settings` as-is. Nothing new to add to `config.yaml`.

### Decisions made at plan time (not deferred to build)

1. **Streamlit, not Gradio or FastAPI+separate frontend.** User's explicit choice (this conversation) after weighing tradeoffs: `st.chat_message` + sidebar + expander primitives map directly onto "answer + evidence panel," and Streamlit Community Cloud gives a one-click shareable demo link for a hiring-manager audience — matching `CLAUDE.md`'s stated portfolio audience. Rejected: Gradio (comparable effort, marginally worse layout fit for a citations/cost sidebar); FastAPI/Flask (would also require hand-building a frontend — more control, not needed when the RAG internals, not the UI, are the point).
2. **Citation metadata is resolved via a new JSON sidecar (`data/index/chunk_metadata.json`), not by adding columns to the LanceDB table.** Rejected: extending `build_vector_index`'s row schema (`src/ingest/vector_index.py:24-34`) to carry chapter/section/page fields. That would touch already-tuned, already-audited index-building code and its existing tests (`tests/ingest/test_vector_index.py`) purely to serve a display concern that has nothing to do with search. A sidecar written once at `ingest` time, read only by the display layer, is fully additive — zero risk to `get_chunk_texts`, `search_vector`, or the BM25 index.
3. **`printed_page_label` stays a `None` passthrough this block — not wired to the bbox-based page-footer detection.** `BUGS.md`'s Ingestion section already flags this exact gap (`classify_page_label` "matches on text shape only, not footer position... needs a bbox-based 'near bottom of page' check before it's trustworthy enough to surface in citations") as unfinished, separate work. `format_citation` degrades gracefully to `"Ch. 4: Energy Management — Total Energy"` (no page number) rather than fabricating one. The bbox fix stays open in `BUGS.md`, out of scope here — building a chat UI is not the moment to also solve page-footer geometry.
4. **Missing-metadata handling is fail-loud in the library, fail-soft in the UI.** `load_chunk_metadata`/`format_citation` raise on a missing key (matches this project's existing convention, e.g. `get_chunk_texts` raising `KeyError` on an unknown id) — a citation the pipeline actually returned must exist in the sidecar it was built from, and silently swallowing that in a library function would hide a real ingest/index drift bug. `streamlit_app.py`'s presentation layer catches that specific exception per citation and falls back to displaying the raw `chunk_id` with a `(citation detail unavailable)` note, so one bad lookup degrades one line of the sources panel instead of crashing the whole chat session mid-conversation.
5. **This is a chat-*styled* UI over independent single-turn queries, not a conversational-memory chat.** `answer_with_verified_citations(question, ...)` takes one flat question with no history parameter; giving it real follow-up resolution ("what about landing?" implicitly referring to the prior turn) would need generation/prompt changes to `src/generate/` — genuinely bigger scope than this block. The UI displays a running thread of past Q&A turns (so it *looks* and *feels* like a chat), but each turn is answered independently, exactly like the CLI's `query` command. This gets stated explicitly in the README so the portfolio framing doesn't overclaim what the system does.
6. **Daily-cost-cap behavior stays warn-only, unchanged from Block 7's decision** (`.agent/decisions.log`, 2026-07-15: "warn-only signal... never a blocking gate... a hard block could interrupt an in-progress eval run with no override"). This block only *adds visibility* — a sidebar banner once `check_budget` returns `True` — it does not change the pipeline's behavior or block further questions.
7. **No Streamlit Community Cloud deployment automation in this block.** Deploying there requires the user's own GitHub-linked Streamlit Cloud account — an action only the user can take, not something `/build` executes. Chunk 10.8's README section documents the deploy path as a manual next step.

## Block 10: Chat Interface

**Success criteria**

- [ ] `data/index/chunk_metadata.json` exists (real corpus, committed), and every `chunk_id` the real corpus's BM25/LanceDB indexes know about resolves to a human-readable citation string via `format_citation` — no query's sources panel shows a raw hex chunk-id.
- [ ] `PYTHONPATH=src streamlit run src/app/streamlit_app.py` runs locally, accepts a question via `st.chat_input`, shows a spinner while the real ~5–10s pipeline call runs (rerank alone measured at ~5.3s/query real-corpus, `BUGS.md` Rerank section), then displays the answer, resolved sources, a low-confidence flag when `coverage < citations.low_confidence_threshold`, and the running daily cost total.
- [ ] A pipeline exception (simulated: a monkeypatched `answer_with_verified_citations` raising) shows `st.error` and leaves the chat session usable for the next question — does not crash the app.
- [ ] `uv run pytest -m "not slow"` stays green with the new tests included; the new AppTest-based tests do not load a real embedding/cross-encoder model or make a real API call (mocks the pipeline call, matching the existing CLI test pattern in `tests/app/test_query_command.py`).
- [ ] `README.md` documents how to run the chat UI locally and names Streamlit Community Cloud as the manual next step for a shareable deploy link; `BUGS.md`'s "raw chunk_id" CLI/CI item is checked off, noting it landed in the chat UI rather than the CLI.

---

### Chunk 10.0 — dependency + real AppTest probe (spike, no production code)

**Files**: Modify `pyproject.toml` (add `streamlit` to `[project.dependencies]`); Create a throwaway scratch script (not committed) to probe `streamlit.testing.v1.AppTest`.

**Step 1 — add the dependency and sync**: add `"streamlit>=1.38"` to `pyproject.toml`'s dependencies list, `uv sync`, confirm `python -c "from streamlit.testing.v1 import AppTest; print(AppTest)"` succeeds under `PYTHONPATH=src` (or just the synced venv — this import doesn't need `src/` on the path).

**Step 2 — probe the real mocking mechanism** — **done, real result**: built a scratch spike (`dummy_app.py` importing `dummy_function` from `dummy_module`, called on a button press / `chat_input`) and tried two mechanisms. **(a) `patch("dummy_app.dummy_function", ...)` before `at.run()` — confirmed NOT to work**: `AppTest` re-executes the entire script fresh on every `.run()` call, including re-running `from dummy_module import dummy_function` each time, which silently overwrites the patched name bound into the script's own namespace. Test asserting the mocked value appeared genuinely failed (`assert False`), not a false pass. **(b) `patch.object(dummy_module, "dummy_function", ...)` — confirmed working**: patching the *source* module's attribute (not the importing script's re-bound name) persists across the re-exec, since the fresh `from dummy_module import dummy_function` picks up the patched attribute at execution time. Verified with both `st.button` and `st.chat_input` — same mechanism holds for both.

**Step 3 — confirmed pattern for Chunk 10.4+**: tests must `patch("citations.pipeline.answer_with_verified_citations", ...)` and `patch("observability.daily_cost.get_daily_total", ...)` — the modules `streamlit_app.py` imports *from*, never `patch("app.streamlit_app.answer_with_verified_citations", ...)` (the re-bound name in the script itself, which the original Chunk 10.4 sketch incorrectly assumed would work). Scratch spike files deleted (scratchpad only, never committed).

**Step 4 — verify `PYTHONPATH` requirement for real**: run `streamlit run src/app/streamlit_app.py` (even though the file doesn't exist yet, run it against `main.py` first: `python -m app.main --help` without `PYTHONPATH=src` set, confirm the `ModuleNotFoundError` actually reproduces) to reconfirm the documented gotcha still holds on this machine before relying on it in Chunk 10.8's README instructions.

**Step 5 — commit**: `git add pyproject.toml uv.lock && git commit -m "[Chore] Deps: add streamlit for the chat UI (Block 10)"`

---

### Chunk 10.1 — `ChunkMetadata` schema + write/load round-trip

**Files**: Create `src/ingest/chunk_metadata.py`, `tests/ingest/test_chunk_metadata.py`.

**Step 1 — write failing test**:
```python
from pathlib import Path

from ingest.chunk_metadata import ChunkMetadata, load_chunk_metadata, write_chunk_metadata


def test_write_then_load_round_trips_metadata(make_chunk, tmp_path):
    chunk = make_chunk("abc123", "some text")
    out_path = tmp_path / "chunk_metadata.json"

    write_chunk_metadata([chunk], out_path)
    loaded = load_chunk_metadata(out_path)

    assert loaded["abc123"] == ChunkMetadata(
        chapter_number=4,
        chapter_title="Energy Management",
        section_title="Total Energy",
        printed_page_label=None,
    )


def test_load_chunk_metadata_raises_on_unknown_id(make_chunk, tmp_path):
    out_path = tmp_path / "chunk_metadata.json"
    write_chunk_metadata([make_chunk("abc123", "text")], out_path)

    loaded = load_chunk_metadata(out_path)

    assert "unknown_id" not in loaded
```

**Step 2 — verify failure**: `uv run pytest tests/ingest/test_chunk_metadata.py -v` → `ModuleNotFoundError: No module named 'ingest.chunk_metadata'`.

**Step 3 — implement minimal code**:
```python
import json
from pathlib import Path

from pydantic import BaseModel

from ingest.models import Chunk


class ChunkMetadata(BaseModel):
    chapter_number: int
    chapter_title: str
    section_title: str
    printed_page_label: str | None = None


def write_chunk_metadata(chunks: list[Chunk], out_path: Path) -> None:
    payload = {
        c.chunk_id: ChunkMetadata(
            chapter_number=c.chapter_number,
            chapter_title=c.chapter_title,
            section_title=c.section_title,
            printed_page_label=c.printed_page_label,
        ).model_dump()
        for c in chunks
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload))


def load_chunk_metadata(path: Path) -> dict[str, ChunkMetadata]:
    raw = json.loads(path.read_text())
    return {chunk_id: ChunkMetadata(**fields) for chunk_id, fields in raw.items()}
```

**Step 4 — verify pass**: `uv run pytest tests/ingest/test_chunk_metadata.py -v` → 2 passed.

**Step 5 — commit**: `git add src/ingest/chunk_metadata.py tests/ingest/test_chunk_metadata.py && git commit -m "[Feature] Ingest: chunk_id -> metadata sidecar (write/load)"`

---

### Chunk 10.2 — `format_citation`

**Files**: Modify `src/ingest/chunk_metadata.py`, `tests/ingest/test_chunk_metadata.py`.

**Step 1 — write failing test**:
```python
def test_format_citation_without_page_label():
    meta = ChunkMetadata(chapter_number=4, chapter_title="Energy Management", section_title="Total Energy")

    assert format_citation(meta) == "Ch. 4: Energy Management — Total Energy"


def test_format_citation_with_page_label():
    meta = ChunkMetadata(
        chapter_number=4, chapter_title="Energy Management", section_title="Total Energy", printed_page_label="4-1"
    )

    assert format_citation(meta) == "Ch. 4: Energy Management — Total Energy, p. 4-1"
```

**Step 2 — verify failure**: `NameError`/`ImportError` — `format_citation` doesn't exist yet.

**Step 3 — implement minimal code**:
```python
def format_citation(meta: ChunkMetadata) -> str:
    page = f", p. {meta.printed_page_label}" if meta.printed_page_label else ""
    return f"Ch. {meta.chapter_number}: {meta.chapter_title} — {meta.section_title}{page}"
```

**Step 4 — verify pass**: both tests green.

**Step 5 — commit**: `git add src/ingest/chunk_metadata.py tests/ingest/test_chunk_metadata.py && git commit -m "[Feature] Ingest: human-readable citation formatting"`

---

### Chunk 10.3 — wire into `ingest` CLI + real re-ingest + commit sidecar

**Files**: Modify `src/app/main.py:28-41` (`ingest` command), `tests/app/test_ingest_command.py`.

**Step 1 — write failing test** (extend the existing test in `tests/app/test_ingest_command.py`):
```python
def test_ingest_command_creates_chunk_metadata_sidecar(make_pdf, tmp_path, isolated_config):
    pdf_path = make_pdf([[
        ("Chapter 4: Energy Management", 14, True),
        ("Total Energy", 10, True),
        ("Body text about total energy in the airplane during flight.", 10, False),
    ]])
    out_dir = tmp_path / "out"

    result = runner.invoke(app, ["ingest", "--pdf", str(pdf_path), "--out", str(out_dir)])

    assert result.exit_code == 0
    assert (out_dir / "chunk_metadata.json").exists()
```

**Step 2 — verify failure**: file doesn't exist, assertion fails.

**Step 3 — implement minimal code** (`src/app/main.py`):
```python
from ingest.chunk_metadata import write_chunk_metadata
...
    build_bm25_index(chunks, out / "bm25")
    build_vector_index(chunks, out / "lancedb")
    write_chunk_metadata(chunks, out / "chunk_metadata.json")
```

**Step 4 — verify pass**: `uv run pytest tests/app/test_ingest_command.py -v` → all green.

**Step 5 — real re-ingest against the actual corpus, verify no drift, then commit**:
```
PYTHONPATH=src uv run python -m app.main ingest --pdf "Airplane Flying Handbook (FAA-H-8083-3C).pdf" --out data/index
PYTHONPATH=src uv run python -m app.main eval --index data/index --retrieval-only
```
Confirm the retrieval-only PASS/FAIL table matches the currently committed baseline exactly (chunking/retrieval logic is unchanged this block — only a new sidecar file is added; any drift here would mean something unexpected changed and must be investigated before committing, not assumed benign). Then:
```
git add src/app/main.py tests/app/test_ingest_command.py data/index/chunk_metadata.json && git commit -m "[Feature] CLI: write chunk metadata sidecar on ingest; regenerate committed index"
```

---

### Chunk 10.4 — Streamlit skeleton (chat input, session history, mocked pipeline)

*(Mocking mechanism confirmed in Chunk 10.0: patch the source modules `streamlit_app.py` imports from — `citations.pipeline.answer_with_verified_citations` / `observability.daily_cost.get_daily_total` — never the re-bound names inside `streamlit_app.py` itself, since `AppTest` re-executes the whole script fresh on every `.run()`.)*

**Files**: Create `src/app/streamlit_app.py`, `tests/app/test_streamlit_app.py`.

**Step 1 — write failing test**:
```python
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


def test_submitting_a_question_shows_the_answer():
    at = AppTest.from_file("src/app/streamlit_app.py")

    class FakeVerified:
        answer_text = "Stalls occur when the critical angle of attack is exceeded."
        citations = []
        coverage = 1.0
        low_confidence = False

    with patch("citations.pipeline.answer_with_verified_citations", return_value=FakeVerified()), \
         patch("observability.daily_cost.get_daily_total", return_value=0.0):
        at.run()
        at.chat_input[0].set_value("What causes a stall?").run()

    assert "Stalls occur when" in at.chat_message[-1].markdown[0].value
```

**Step 2 — verify failure**: `src/app/streamlit_app.py` doesn't exist yet → collection error.

**Step 3 — implement minimal code**:
```python
import streamlit as st
import anthropic

from citations.pipeline import answer_with_verified_citations
from config import get_settings
from observability.daily_cost import get_daily_total

st.set_page_config(page_title="Ask My Docs — FAA Airplane Flying Handbook")
st.title("Ask My Docs")

if "history" not in st.session_state:
    st.session_state.history = []

settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])

question = st.chat_input("Ask a question about the Airplane Flying Handbook")
if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    result = answer_with_verified_citations(question, client, settings=settings, bm25_dir=..., vector_db_path=...)
    with st.chat_message("assistant"):
        st.markdown(result.answer_text)
    st.session_state.history.append({"role": "assistant", "content": result.answer_text})
```
(Index paths resolved from a `data/index` default, matching `main.py`'s `Path("data/index")` default — finalize exact plumbing in this chunk's real implementation, not just the sketch above.)

**Step 4 — verify pass**: `uv run pytest tests/app/test_streamlit_app.py -v` → green, no real model load, no real API call.

**Step 5 — commit**: `git add src/app/streamlit_app.py tests/app/test_streamlit_app.py && git commit -m "[Feature] Chat UI: Streamlit skeleton with chat input and session history"`

---

### Chunk 10.5 — real pipeline wiring, sources panel, low-confidence flag, spinner

**Files**: Modify `src/app/streamlit_app.py`, `tests/app/test_streamlit_app.py`.

**Step 1 — write failing test**: extend `FakeVerified` in the test to include real citation ids (`citations = ["abc123"]`, `coverage = 0.4`, `low_confidence = True`), patch `ingest.chunk_metadata.load_chunk_metadata` (source module, per the confirmed Chunk 10.0 mechanism) to return a fixed `{"abc123": ChunkMetadata(...)}`, and assert (a) the sources panel shows `format_citation`'s human-readable string, not `"abc123"`, and (b) a low-confidence warning renders (`at.warning` or equivalent element non-empty) when `low_confidence=True`.

**Step 2 — verify failure**: sources panel doesn't exist yet in the skeleton.

**Step 3 — implement minimal code**: wrap the pipeline call in `with st.spinner("Searching the handbook..."):` (justified by the measured ~5.3s/query real rerank latency, `BUGS.md` Rerank section — a multi-second wait with no feedback reads as a frozen app). After the call, load `chunk_metadata.json` once (cache with `@st.cache_resource` — safe, the sidecar is static per index build) and render each citation via `format_citation`, catching a missing-key lookup per Decision 4 and falling back to the raw id with a `(citation detail unavailable)` note. Render `st.warning(...)` when `result.low_confidence`.

**Step 4 — verify pass**: extended test green.

**Step 5 — commit**: `git add src/app/streamlit_app.py tests/app/test_streamlit_app.py && git commit -m "[Feature] Chat UI: resolved sources panel, low-confidence flag, loading spinner"`

---

### Chunk 10.6 — sidebar: daily cost total + budget-cap banner

**Files**: Modify `src/app/streamlit_app.py`, `tests/app/test_streamlit_app.py`.

**Step 1 — write failing test**: patch `observability.daily_cost.get_daily_total` (and `observability.daily_cost.check_budget`, source modules) to return a value above the configured `daily_cost_cap_usd`, assert a budget-cap warning renders in the sidebar; patch it below the cap, assert no warning.

**Step 2 — verify failure**: sidebar cost display doesn't exist yet.

**Step 3 — implement minimal code**: `st.sidebar.metric("Today's cost", f"${get_daily_total(...):.4f}")`; reuse `check_budget` (`src/observability/daily_cost.py`, already exists, not yet called from any CLI/UI surface per the reuse audit) to decide whether to render `st.sidebar.warning(...)` — read-only visibility per Decision 6, no new blocking behavior.

**Step 4 — verify pass**: both branches of the new test green.

**Step 5 — commit**: `git add src/app/streamlit_app.py tests/app/test_streamlit_app.py && git commit -m "[Feature] Chat UI: sidebar daily cost total and budget-cap banner"`

---

### Chunk 10.7 — pipeline-error resilience

**Files**: Modify `src/app/streamlit_app.py`, `tests/app/test_streamlit_app.py`.

**Step 1 — write failing test**: patch `citations.pipeline.answer_with_verified_citations` (source module) to `side_effect=RuntimeError("boom")`, submit a question, assert `st.error(...)` renders (not an unhandled exception) and that submitting a second, non-erroring question afterward still works in the same session.

**Step 2 — verify failure**: an uncaught exception currently propagates and (depending on `AppTest`'s behavior, confirm via the test itself) either fails the test run or leaves `at.exception` non-empty.

**Step 3 — implement minimal code**: wrap the pipeline call in `try/except Exception as e: st.error(f"Something went wrong answering that question: {e}")`, and make sure the failed turn does not get appended to `st.session_state.history` as a phantom assistant message.

**Step 4 — verify pass**: both assertions (error shown, session still usable) green.

**Step 5 — commit**: `git add src/app/streamlit_app.py tests/app/test_streamlit_app.py && git commit -m "[Fix] Chat UI: surface pipeline errors without crashing the session"`

---

### Chunk 10.8 — docs: README section, BUGS.md checkoff, decisions.log

**Files**: Modify `README.md`, `BUGS.md`, `.agent/decisions.log`.

**Step 1 — capture real output**: run `PYTHONPATH=src streamlit run src/app/streamlit_app.py` locally, ask a real question against the real corpus, screenshot the result (answer + resolved sources + coverage flag + sidebar cost) for the README, matching this project's "every command/claim is verified against something real" convention already established in Block 9.

**Step 2 — write the README section**: add a "Chat Interface" section — what it is (chat-styled UI over the existing pipeline, per Decision 5's precise framing — not conversational memory), how to run it locally (`uv sync`, `PYTHONPATH=src streamlit run src/app/streamlit_app.py`, real command verified in Step 1), the real screenshot, and a short "Deploying" note naming Streamlit Community Cloud as the manual next step (link the app to the GitHub repo from the user's own Streamlit Cloud account — explicitly a user action, not automated here per Decision 7).

**Step 3 — checkoff BUGS.md**: mark the CLI/CI section's raw-chunk-id item resolved, noting it landed as the chat UI's `format_citation` rather than a CLI-output change, and cross-reference this plan file.

**Step 4 — decisions.log**: append this block's numbered decisions (1–7 above) in the established `[YYYY-MM-DD] [Ask My Docs / <Area>] — Decision (...)` format.

**Step 5 — commit**: `git add README.md BUGS.md .agent/decisions.log docs/images/<screenshot>.png && git commit -m "[Docs] Chat UI: README section, BUGS.md closeout, decisions log"`

---

## Technical Debt Strategy

- `printed_page_label` stays unwired (pre-existing debt, `BUGS.md` Ingestion section — not newly introduced, explicitly not fixed here per Decision 3).
- No conversational memory/follow-up resolution (Decision 5) — an honest scope limit, not a shortcut to fix later unless a future block decides multi-turn RAG is worth the generation/prompt redesign it needs.
- No automated visual/CSS regression testing for the Streamlit UI — `AppTest` checks element tree and text content, not pixel-level rendering. Acceptable for a portfolio chat UI; would matter more for a UI with actual design-system requirements (this project has none — `CLAUDE.md`: "`ui-development` does not [apply] (no frontend)").
- Chat history is `st.session_state`-only — resets on a page refresh or new browser session. No persistence layer. Fine for a demo; would need a real store (not scoped here) for a multi-session product.
- `chunk_metadata.json` is a second index-adjacent artifact that must stay in sync with the BM25/LanceDB indexes (same class of risk `BUGS.md`'s Config section already flags for other index-lifetime concerns) — if the corpus is ever re-ingested without also regenerating this file, citations would silently fail to resolve for new chunk ids. No automated check enforces this today; revisit if re-ingestion becomes a repeated/scripted operation rather than the rare, manual, fully-re-verified event it has been so far.

## Production & Design Standards (P0)

- **Timeout Mapping**: inherited, not re-implemented — `GenerationConfig.timeout_seconds`/`CitationConfig.timeout_seconds` (both `30.0`, already config-driven) already bound every real API call `answer_with_verified_citations` makes. The UI adds no new network call of its own.
- **Error Handling**: Chunk 10.7 (`st.error` + the underlying pipeline's own `logging.warning` calls, e.g. `report_usage`'s budget-cap warning) — no `console.error`/`toast` equivalent needed, this isn't a JS frontend; Streamlit's own error rendering is the analogous mechanism.
- **Loading States**: Chunk 10.5's `st.spinner`, justified by the measured real rerank latency (~5.3s/query, `BUGS.md`) rather than a generic checklist requirement.

## For UI Features

- No `.interface-design/system.md` exists (confirmed: not present in repo) and none is warranted — `CLAUDE.md` states this project has no frontend/design-system scope; Streamlit's built-in `st.chat_message`/sidebar/spinner components are used as-is, no custom design system created.

---

Ready to start building? Use `/build`.
