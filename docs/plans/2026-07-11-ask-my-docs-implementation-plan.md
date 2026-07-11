# Ask My Docs — Implementation Plan (Block 0 + Block 1: Environment & Ingestion)

**Date**: 2026-07-11
**Status**: Ready for `/build`
**Source design**: `docs/plans/2026-07-10-ask-my-docs-design.md`

## Scope of this plan

Per user decision on 2026-07-11: this document gives **full TDD chunk detail** (exact test code, RED/GREEN/REFACTOR steps) for **Block 0** (environment/config scaffolding) and **Block 1** (PDF ingestion & chunking) only — the immediate next work, and the block whose real output shapes (the `Chunk` schema, chunk IDs, index formats) everything downstream depends on.

Blocks 2–9 (retrieval, reranking, generation, citation verification, eval harness, observability, CLI completion, CI, portfolio polish) are sketched at block/chunk-list level in **"Remaining Blocks (to be detailed later)"** below, with their own `/plan` pass planned once Block 1 lands and we can see real chunk data. Writing exact test code for those now would mean designing against guessed data shapes rather than real ones.

## Header

- **Goal**: Stand up a reproducible Python environment, a config-driven settings system, and a fully tested PDF→Chunk ingestion pipeline that writes a BM25 index and a LanceDB vector index — the foundation every later pipeline stage reads from.
- **Architecture**: `src/`-layout Python project (packages live directly under `src/`, added to `pythonpath` via pytest config — no installed package needed for local dev). Ingestion is a pure function pipeline: `PDF path → raw blocks (pymupdf) → headers/boundaries → grouped+windowed text → Chunk objects → indexes on disk`. Every stage is independently unit-testable against small synthetic PDFs built in-memory with `fitz`, never against the real 273MB handbook.
- **Design Patterns**: Pipeline/pure-functions over classes where possible (each ingestion stage is a testable function, not a stateful object). Pydantic models as the data contract between stages. A settings singleton (pydantic-settings) is the one piece of shared state, injected as a parameter, not imported as a global, into anything that needs config.
- **Tech Stack**: `uv` (Python + dependency management), `pydantic` / `pydantic-settings` (config), `pymupdf` (PDF parsing), `bm25s` (sparse index), `sentence-transformers` (`bge-small-en-v1.5`, dense embeddings), `lancedb` (vector store), `tiktoken` (token counting for chunk sizing — see note below), `typer` (CLI), `pytest`.

### Plan-time addition to the design doc's library table

The design doc specifies chunk sizing in **tokens** (400–600 token subsections, 15% overlap) but didn't name a tokenizer. Word-count is not an accurate proxy for token count. Adding **`tiktoken`** (pure CPU, no GPU, ~few MB, offline after first download of its encoding file) as the token-counting utility for the chunker only — not used anywhere else in the pipeline. This should be logged to `.agent/decisions.log` when `/build` executes Chunk 1.6 (sliding-window fallback), since that's the first chunk that actually needs it.

## Environment reality check (verified this session)

- No system Python is installed (`python`/`python3`/`py` all fail — only Windows Store stub aliases exist).
- `uv` **is** installed at `C:\Users\gokul\.local\bin\uv.exe`, and it already has **Python 3.11.8** installed and managed (`cpython-3.11.8-windows-x86_64-none`) — satisfies the "Python 3.11+" requirement with zero extra install steps.
- **Decision**: use `uv` for both Python version pinning and dependency management (`uv venv`, `uv add`, `uv run`). No `pip`/`venv`/`requirements.txt` workflow needed — `pyproject.toml` + `uv.lock` is the source of truth. This is a deviation from the design doc's `requirements.txt` in the repo tree; `requirements.txt` will be generated via `uv export` for anyone without `uv`, but `pyproject.toml`/`uv.lock` are canonical.

---

## Block 0: Environment & Config Scaffolding

### Success Criteria
- [ ] `uv run pytest` executes successfully from repo root with zero tests (empty suite passes) before any test files exist.
- [ ] `Settings` loads defaults from `config.yaml`, overrides from `.env`, and raises a clear validation error when a required field (e.g. `anthropic_api_key`) is missing.
- [ ] No secret ever has a hardcoded fallback default — secrets are required fields with no default value.

### Chunk 0.1 — `uv`-managed environment + project scaffolding

This is project/environment setup, not application behavior — no test-first cycle applies here (matches the documented TDD exception for "configuration files" / tooling scaffolding). Still done as one atomic, verifiable chunk.

**Files**: Create: `pyproject.toml`, `.python-version`, `pytest.ini` (or `[tool.pytest.ini_options]` in `pyproject.toml`), `src/__init__.py`-free package dirs (`src/ingest/`, `src/retrieval/`, `src/rerank/`, `src/generate/`, `src/citations/`, `src/eval/`, `src/observability/`, `src/config/`, `src/app/`, each with `__init__.py`), `tests/` (mirroring the same subpackage names), `.gitignore` additions for `.venv/`, `data/`, `*.lance/`.

**Step 1: Set up**
```bash
uv python pin 3.11
uv init --no-readme --name ask-my-docs
uv add pydantic pydantic-settings[yaml] pymupdf bm25s sentence-transformers lancedb tiktoken anthropic langfuse typer
uv add --dev pytest
```

**Step 2: Configure pytest to see `src/` without installing the package**

In `pyproject.toml`:
```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

**Step 3: Verify**
```bash
uv run pytest
```
Expected output: `no tests ran` / `collected 0 items` — exit code 0, not an error. This proves the venv, interpreter, and pytest config are all wired correctly before any real code exists.

**Step 4: Commit**
```bash
git add pyproject.toml .python-version uv.lock pytest.ini src tests .gitignore
git commit -m "[Setup] Environment: bootstrap uv-managed Python 3.11 project with src-layout packages"
```

### Chunk 0.2 — `Settings`: config-driven, no magic numbers

**Files**: Create: `src/config/settings.py`, `src/config/__init__.py` (re-export `Settings`, `get_settings`), `tests/config/test_settings.py`, `config.yaml`, `config.example.yaml`, `.env.example`.

**Step 1: Write failing test**
```python
# tests/config/test_settings.py
import pytest
from pydantic import ValidationError

from config.settings import Settings


def test_loads_chunking_defaults_from_yaml(tmp_path, monkeypatch):
    yaml_content = """
chunking:
  min_tokens: 400
  max_tokens: 600
  overlap_pct: 0.15
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml_content)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    settings = Settings(_yaml_file=config_file)

    assert settings.chunking.min_tokens == 400
    assert settings.chunking.max_tokens == 600
    assert settings.chunking.overlap_pct == 0.15


def test_missing_required_secret_raises_validation_error(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("chunking:\n  min_tokens: 400\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_yaml_file=config_file, _env_file=None)


def test_env_var_overrides_yaml_value(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("retrieval:\n  rrf_k: 60\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("RETRIEVAL__RRF_K", "30")

    settings = Settings(_yaml_file=config_file)

    assert settings.retrieval.rrf_k == 30
```

**Step 2: Verify failure**
```bash
uv run pytest tests/config/test_settings.py -v
```
Expected: `ModuleNotFoundError: No module named 'config.settings'` (or `ImportError`) — fails because the module doesn't exist yet, not because of a typo.

**Step 3: Implement minimal code**
```python
# src/config/settings.py
from pathlib import Path
from typing import Type, Tuple

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class ChunkingConfig(BaseModel):
    min_tokens: int = 400
    max_tokens: int = 600
    overlap_pct: float = 0.15


class RetrievalConfig(BaseModel):
    rrf_k: int = 60
    bm25_weight: float = 1.0
    vector_weight: float = 1.0
    top_n: int = 20


class RerankConfig(BaseModel):
    enabled: bool = True
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k: int = 5


class GenerationConfig(BaseModel):
    model: str = "claude-sonnet-4-5"  # verify against current Anthropic model list at build time
    max_retries: int = 3
    backoff_base_seconds: float = 1.0


class CitationConfig(BaseModel):
    low_confidence_threshold: float = 0.7


class EvalConfig(BaseModel):
    judge_model: str = "claude-haiku-4-5-20251001"  # verify against current Anthropic model list at build time
    judge_temperature: float = 0.0


class ObservabilityConfig(BaseModel):
    langfuse_enabled: bool = True
    daily_cost_cap_usd: float = 5.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        yaml_file="config.yaml",
        extra="ignore",
    )

    anthropic_api_key: str
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    citations: CitationConfig = Field(default_factory=CitationConfig)
    eval: EvalConfig = Field(default_factory=EvalConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def get_settings() -> Settings:
    return Settings()
```

```python
# src/config/__init__.py
from config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
```

`config.yaml` (defaults checked into the repo — no secrets):
```yaml
chunking:
  min_tokens: 400
  max_tokens: 600
  overlap_pct: 0.15

retrieval:
  rrf_k: 60
  bm25_weight: 1.0
  vector_weight: 1.0
  top_n: 20

rerank:
  enabled: true
  model: cross-encoder/ms-marco-MiniLM-L-6-v2
  top_k: 5

generation:
  model: claude-sonnet-4-5
  max_retries: 3
  backoff_base_seconds: 1.0

citations:
  low_confidence_threshold: 0.7

eval:
  judge_model: claude-haiku-4-5-20251001
  judge_temperature: 0.0

observability:
  langfuse_enabled: true
  daily_cost_cap_usd: 5.0
```

`config.example.yaml`: identical copy (committed as the documented template per repo structure in the design doc).

`.env.example`:
```
ANTHROPIC_API_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

**Step 4: Verify pass**
```bash
uv run pytest tests/config/test_settings.py -v
```
Expected: 3 passed.

**Step 5: Commit**
```bash
git add src/config tests/config config.yaml config.example.yaml .env.example
git commit -m "[Feature] Config: add pydantic-settings Settings with yaml+env layering and required-secret validation"
```

**Note on defaults above**: `rrf_k`, `low_confidence_threshold`, `daily_cost_cap_usd`, `rerank.top_k` etc. are reasonable starting points, not empirically tuned — the design doc calls these out as config-driven precisely so they can move without code changes once the eval harness (Block 6) gives real signal on what values are good.

---

## Block 1: Ingestion — PDF → Chunks → Indexes

### Success Criteria
- [ ] `chunk_pdf()` run twice on the same PDF produces byte-identical chunk IDs (re-ingestion stability).
- [ ] A subsection spanning more than `max_tokens` is split into overlapping windows; a subsection under the limit is not split.
- [ ] Figure captions (`Figure N-N. ...`) are captured as chunk metadata, never left to corrupt chunk body text.
- [ ] BM25 and vector indexes both round-trip: build → reload → search returns the expected chunk for an unambiguous query.
- [ ] All ingestion unit tests run against small synthetic PDFs built in-memory with `fitz` — none depend on the real 273MB handbook being present.
- [ ] `uv run python -m app ingest --pdf <path> --out <dir>` runs the full pipeline end to end.

### Conventions for this block
- **Test fixtures**: no checked-in binary PDF fixtures. Every test builds its input PDF programmatically via a shared `make_pdf()` helper in `tests/ingest/conftest.py`, using PyMuPDF's own document-writing API (`fitz.open()` new doc + `page.insert_text(..., fontname=...)`). Built-in font names `"helv"` (regular) and `"hebo"` (bold) are used to control the `bold` flag PyMuPDF reports back on extraction — this is a real, documented PyMuPDF mechanism, not a mock.
- **Reuse audit**: greenfield module — no existing equivalents in this repo. "No existing equivalent found" for every function below.
- **Slow tests**: Chunk 1.11 (vector index) downloads and runs `bge-small-en-v1.5` locally. Mark that test `@pytest.mark.slow` so the fast dev loop (`uv run pytest -m "not slow"`) skips it; CI's cheap-gate (Block 8) still runs it since it's a free local model, not a paid API call.

### Chunk 1.1 — Extract raw text spans with font metadata

**Files**: Create: `src/ingest/models.py` (add `TextSpan`), `src/ingest/pdf_loader.py`, `tests/ingest/conftest.py`, `tests/ingest/test_pdf_loader.py`.

**Step 1: Write failing test**
```python
# tests/ingest/conftest.py
from pathlib import Path
import fitz
import pytest


@pytest.fixture
def make_pdf(tmp_path):
    def _make_pdf(pages: list[list[tuple[str, int, bool]]]) -> Path:
        """pages: list of pages; each page is a list of (text, font_size, bold) lines."""
        doc = fitz.open()
        for lines in pages:
            page = doc.new_page()
            y = 72
            for text, size, bold in lines:
                fontname = "hebo" if bold else "helv"
                page.insert_text((72, y), text, fontsize=size, fontname=fontname)
                y += size + 10
        path = tmp_path / "test.pdf"
        doc.save(path)
        doc.close()
        return path

    return _make_pdf
```

```python
# tests/ingest/test_pdf_loader.py
from ingest.pdf_loader import extract_page_spans


def test_extracts_text_and_font_metadata(make_pdf):
    pdf_path = make_pdf([
        [("Chapter 4: Energy Management", 14, True), ("Body text here.", 10, False)],
    ])

    spans = extract_page_spans(pdf_path)

    assert len(spans) == 2
    assert spans[0].text == "Chapter 4: Energy Management"
    assert spans[0].is_bold is True
    assert spans[0].font_size == 14
    assert spans[0].page_index == 0
    assert spans[1].text == "Body text here."
    assert spans[1].is_bold is False
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_pdf_loader.py -v
```
Expected: `ModuleNotFoundError: No module named 'ingest.pdf_loader'`.

**Step 3: Implement minimal code**
```python
# src/ingest/models.py
from pydantic import BaseModel


class TextSpan(BaseModel):
    text: str
    font_size: float
    is_bold: bool
    page_index: int
    bbox: tuple[float, float, float, float]
```

```python
# src/ingest/pdf_loader.py
from pathlib import Path

import fitz

from ingest.models import TextSpan

BOLD_FLAG = 1 << 4  # PyMuPDF span flag bit for bold


def extract_page_spans(pdf_path: Path) -> list[TextSpan]:
    doc = fitz.open(pdf_path)
    spans: list[TextSpan] = []
    for page_index, page in enumerate(doc):
        raw = page.get_text("dict")
        for block in raw["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    text = span["text"].strip()
                    if not text:
                        continue
                    spans.append(
                        TextSpan(
                            text=text,
                            font_size=span["size"],
                            is_bold=bool(span["flags"] & BOLD_FLAG),
                            page_index=page_index,
                            bbox=tuple(span["bbox"]),
                        )
                    )
    doc.close()
    return spans
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_pdf_loader.py -v
```
Expected: 1 passed.

**Step 5: Commit**
```bash
git add src/ingest/models.py src/ingest/pdf_loader.py tests/ingest/conftest.py tests/ingest/test_pdf_loader.py
git commit -m "[Feature] Ingest: extract text spans with font-size/bold metadata via PyMuPDF"
```

### Chunk 1.2 — Detect chapter headers

**Files**: Create: `src/ingest/headers.py` (add `detect_chapter_headers`), `src/ingest/models.py` (add `ChapterHeader`), `tests/ingest/test_headers.py`.

**Step 1: Write failing test**
```python
# tests/ingest/test_headers.py
from ingest.pdf_loader import extract_page_spans
from ingest.headers import detect_chapter_headers


def test_detects_chapter_header_line(make_pdf):
    pdf_path = make_pdf([
        [("Chapter 4: Energy Management", 14, True), ("Some body text.", 10, False)],
    ])
    spans = extract_page_spans(pdf_path)

    chapters = detect_chapter_headers(spans)

    assert len(chapters) == 1
    assert chapters[0].chapter_number == 4
    assert chapters[0].title == "Energy Management"
    assert chapters[0].page_index == 0


def test_ignores_non_chapter_body_text(make_pdf):
    pdf_path = make_pdf([
        [("Chapter Four Overview", 10, False), ("This chapter covers energy.", 10, False)],
    ])
    spans = extract_page_spans(pdf_path)

    chapters = detect_chapter_headers(spans)

    assert chapters == []
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_headers.py -v
```
Expected: `ModuleNotFoundError: No module named 'ingest.headers'`.

**Step 3: Implement minimal code**
```python
# src/ingest/models.py — add
class ChapterHeader(BaseModel):
    chapter_number: int
    title: str
    page_index: int
```

```python
# src/ingest/headers.py
import re

from ingest.models import ChapterHeader, TextSpan

CHAPTER_PATTERN = re.compile(r"^Chapter (\d+): (.+)$")


def detect_chapter_headers(spans: list[TextSpan]) -> list[ChapterHeader]:
    headers = []
    for span in spans:
        match = CHAPTER_PATTERN.match(span.text)
        if match:
            headers.append(
                ChapterHeader(
                    chapter_number=int(match.group(1)),
                    title=match.group(2),
                    page_index=span.page_index,
                )
            )
    return headers
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_headers.py -v
```
Expected: 2 passed.

**Step 5: Commit**
```bash
git add src/ingest/headers.py src/ingest/models.py tests/ingest/test_headers.py
git commit -m "[Feature] Ingest: detect chapter headers via regex on extracted text"
```

### Chunk 1.3 — Detect subsection headers via font metadata (not regex)

**Files**: Modify: `src/ingest/headers.py` (add `detect_subsection_headers`), `src/ingest/models.py` (add `SubsectionHeader`), `tests/ingest/test_headers.py`.

**Step 1: Write failing test**
```python
# tests/ingest/test_headers.py — add
from ingest.headers import detect_subsection_headers


def test_detects_bold_line_as_subsection_header(make_pdf):
    pdf_path = make_pdf([[
        ("Chapter 4: Energy Management", 14, True),
        ("Total Energy", 10, True),          # bold, same size as body -> header by boldness
        ("Body text explaining energy.", 10, False),
        ("Body text continues here.", 10, False),
    ]])
    spans = extract_page_spans(pdf_path)

    subsections = detect_subsection_headers(spans)

    assert [s.title for s in subsections] == ["Total Energy"]


def test_detects_larger_font_line_as_subsection_header(make_pdf):
    pdf_path = make_pdf([[
        ("Chapter 4: Energy Management", 14, True),
        ("Total Energy", 13, False),          # larger, non-bold -> header by size
        ("Body text explaining energy.", 10, False),
    ]])
    spans = extract_page_spans(pdf_path)

    subsections = detect_subsection_headers(spans)

    assert [s.title for s in subsections] == ["Total Energy"]


def test_does_not_flag_plain_body_text_as_header(make_pdf):
    pdf_path = make_pdf([[
        ("Chapter 4: Energy Management", 14, True),
        ("Body text explaining energy in detail.", 10, False),
    ]])
    spans = extract_page_spans(pdf_path)

    subsections = detect_subsection_headers(spans)

    assert subsections == []
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_headers.py -v
```
Expected: `AttributeError`/`ImportError` — `detect_subsection_headers` doesn't exist yet.

**Step 3: Implement minimal code**

Heuristic: the chapter-header line and any line whose text matches `Figure N-N.` are excluded up front. Of what remains, a line is a subsection header if it is **bold**, or its font size exceeds the page's most common ("body") font size by a configurable ratio. Body size is computed as the mode of all non-header candidate sizes on that page.

```python
# src/ingest/models.py — add
class SubsectionHeader(BaseModel):
    title: str
    page_index: int
    font_size: float
    is_bold: bool
```

```python
# src/ingest/headers.py — add
from collections import Counter

from ingest.models import SubsectionHeader

CHAPTER_HEADER_TEXT = CHAPTER_PATTERN
FIGURE_CAPTION_PATTERN = re.compile(r"^Figure \d+-\d+\.")
SIZE_RATIO_THRESHOLD = 1.15


def detect_subsection_headers(spans: list[TextSpan]) -> list[SubsectionHeader]:
    by_page: dict[int, list[TextSpan]] = {}
    for span in spans:
        by_page.setdefault(span.page_index, []).append(span)

    headers: list[SubsectionHeader] = []
    for page_index, page_spans in by_page.items():
        candidates = [
            s
            for s in page_spans
            if not CHAPTER_HEADER_TEXT.match(s.text)
            and not FIGURE_CAPTION_PATTERN.match(s.text)
        ]
        if not candidates:
            continue

        body_size = Counter(s.font_size for s in candidates).most_common(1)[0][0]

        for span in candidates:
            is_header = span.is_bold or span.font_size > body_size * SIZE_RATIO_THRESHOLD
            if is_header and span.font_size == body_size and not span.is_bold:
                continue  # body-sized, non-bold text is never a header
            if is_header:
                headers.append(
                    SubsectionHeader(
                        title=span.text,
                        page_index=page_index,
                        font_size=span.font_size,
                        is_bold=span.is_bold,
                    )
                )
    return headers
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_headers.py -v
```
Expected: 5 passed.

**Step 5: Commit**
```bash
git add src/ingest/headers.py src/ingest/models.py tests/ingest/test_headers.py
git commit -m "[Feature] Ingest: detect subsection headers via font-size/bold metadata heuristic"
```

**Technical debt flag**: `SIZE_RATIO_THRESHOLD = 1.15` is a guessed constant, untested against the real handbook's actual font sizes. First thing to spot-check once the real PDF is run through this pipeline (see Technical Debt Strategy below).

### Chunk 1.4 — Extract dual page-number labels

**Files**: Create: `src/ingest/page_labels.py`, `tests/ingest/test_page_labels.py`.

**Step 1: Write failing test**
```python
# tests/ingest/test_page_labels.py
from ingest.page_labels import classify_page_label


def test_classifies_roman_numeral_front_matter_label():
    assert classify_page_label("iii") == "iii"
    assert classify_page_label("xiv") == "xiv"


def test_classifies_chapter_relative_body_label():
    assert classify_page_label("4-1") == "4-1"
    assert classify_page_label("12-23") == "12-23"


def test_returns_none_for_unrelated_text():
    assert classify_page_label("Total Energy") is None
    assert classify_page_label("Chapter 4: Energy Management") is None
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_page_labels.py -v
```
Expected: `ModuleNotFoundError: No module named 'ingest.page_labels'`.

**Step 3: Implement minimal code**
```python
# src/ingest/page_labels.py
import re

ROMAN_PATTERN = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
CHAPTER_RELATIVE_PATTERN = re.compile(r"^\d+-\d+$")


def classify_page_label(text: str) -> str | None:
    if ROMAN_PATTERN.match(text) or CHAPTER_RELATIVE_PATTERN.match(text):
        return text
    return None
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_page_labels.py -v
```
Expected: 3 passed.

**Step 5: Commit**
```bash
git add src/ingest/page_labels.py tests/ingest/test_page_labels.py
git commit -m "[Feature] Ingest: classify roman-numeral and chapter-relative printed page labels"
```

**Technical debt flag**: this classifies label *text*, not label *position* — it doesn't yet confirm the match came from a page footer. A body sentence that happens to contain a lone `"4-1"`-shaped token would false-positive. Deferred to a REFACTOR pass once ingestion runs against real pages and we can see whether this actually happens (see Technical Debt Strategy).

### Chunk 1.5 — Extract figure caption references

**Files**: Create: `src/ingest/figures.py`, `tests/ingest/test_figures.py`.

**Step 1: Write failing test**
```python
# tests/ingest/test_figures.py
from ingest.figures import extract_figure_ref


def test_extracts_figure_number_and_caption():
    ref = extract_figure_ref("Figure 4-3. Forces acting on an airplane in a turn.")
    assert ref is not None
    assert ref.figure_number == "4-3"
    assert ref.caption == "Forces acting on an airplane in a turn."


def test_returns_none_for_non_figure_text():
    assert extract_figure_ref("Total Energy") is None
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_figures.py -v
```
Expected: `ModuleNotFoundError: No module named 'ingest.figures'`.

**Step 3: Implement minimal code**
```python
# src/ingest/models.py — add
class FigureRef(BaseModel):
    figure_number: str
    caption: str
```

```python
# src/ingest/figures.py
import re

from ingest.models import FigureRef

FIGURE_PATTERN = re.compile(r"^Figure (\d+-\d+)\.\s+(.+)$")


def extract_figure_ref(text: str) -> FigureRef | None:
    match = FIGURE_PATTERN.match(text)
    if not match:
        return None
    return FigureRef(figure_number=match.group(1), caption=match.group(2))
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_figures.py -v
```
Expected: 2 passed.

**Step 5: Commit**
```bash
git add src/ingest/figures.py src/ingest/models.py tests/ingest/test_figures.py
git commit -m "[Feature] Ingest: extract figure number and caption as chunk metadata hook"
```

### Chunk 1.6 — Deterministic chunk ID

**Files**: Create: `src/ingest/chunk_id.py`, `tests/ingest/test_chunk_id.py`.

**Step 1: Write failing test**
```python
# tests/ingest/test_chunk_id.py
from ingest.chunk_id import make_chunk_id


def test_same_inputs_produce_same_id():
    id1 = make_chunk_id(chapter_number=4, section_title="Total Energy", sequence=0)
    id2 = make_chunk_id(chapter_number=4, section_title="Total Energy", sequence=0)
    assert id1 == id2


def test_different_sequence_produces_different_id():
    id1 = make_chunk_id(chapter_number=4, section_title="Total Energy", sequence=0)
    id2 = make_chunk_id(chapter_number=4, section_title="Total Energy", sequence=1)
    assert id1 != id2


def test_different_section_title_produces_different_id():
    id1 = make_chunk_id(chapter_number=4, section_title="Total Energy", sequence=0)
    id2 = make_chunk_id(chapter_number=4, section_title="Kinetic Energy", sequence=0)
    assert id1 != id2
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_chunk_id.py -v
```
Expected: `ModuleNotFoundError: No module named 'ingest.chunk_id'`.

**Step 3: Implement minimal code**
```python
# src/ingest/chunk_id.py
import hashlib


def make_chunk_id(chapter_number: int, section_title: str, sequence: int) -> str:
    key = f"{chapter_number}|{section_title}|{sequence}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_chunk_id.py -v
```
Expected: 3 passed.

**Step 5: Commit**
```bash
git add src/ingest/chunk_id.py tests/ingest/test_chunk_id.py
git commit -m "[Feature] Ingest: deterministic content-hash chunk IDs stable across re-ingestion"
```

### Chunk 1.7 — Token counting for chunk sizing

**Files**: Create: `src/ingest/tokens.py`, `tests/ingest/test_tokens.py`.

**Step 1: Write failing test**
```python
# tests/ingest/test_tokens.py
from ingest.tokens import count_tokens


def test_counts_tokens_for_short_text():
    assert count_tokens("Hello world") > 0


def test_longer_text_has_more_tokens_than_shorter_text():
    short = count_tokens("Energy management.")
    long = count_tokens("Energy management is the demonstrated ability to control total energy.")
    assert long > short
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_tokens.py -v
```
Expected: `ModuleNotFoundError: No module named 'ingest.tokens'`.

**Step 3: Implement minimal code**
```python
# src/ingest/tokens.py
import tiktoken

_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_tokens.py -v
```
Expected: 2 passed.

**Step 5: Commit**
```bash
git add src/ingest/tokens.py tests/ingest/test_tokens.py
git commit -m "[Feature] Ingest: add tiktoken-based token counting for chunk sizing"
```

*(This is the point at which `/build` should log the tiktoken addition to `.agent/decisions.log`, per the note in this plan's header.)*

### Chunk 1.8 — Group spans into subsection-boundary chunks

**Files**: Create: `src/ingest/chunker.py` (add `group_into_sections`), `src/ingest/models.py` (add `Chunk`), `tests/ingest/test_chunker.py`.

**Step 1: Write failing test**
```python
# tests/ingest/test_chunker.py
from ingest.pdf_loader import extract_page_spans
from ingest.headers import detect_chapter_headers, detect_subsection_headers
from ingest.chunker import group_into_sections


def test_groups_body_text_under_its_subsection_header(make_pdf):
    pdf_path = make_pdf([[
        ("Chapter 4: Energy Management", 14, True),
        ("Total Energy", 10, True),
        ("Body text about total energy.", 10, False),
        ("More body text about total energy.", 10, False),
        ("Kinetic Energy", 10, True),
        ("Body text about kinetic energy.", 10, False),
    ]])
    spans = extract_page_spans(pdf_path)
    chapters = detect_chapter_headers(spans)
    subsections = detect_subsection_headers(spans)

    sections = group_into_sections(spans, chapters, subsections)

    assert len(sections) == 2
    assert sections[0].section_title == "Total Energy"
    assert "Body text about total energy." in sections[0].text
    assert "More body text about total energy." in sections[0].text
    assert sections[1].section_title == "Kinetic Energy"
    assert "Body text about kinetic energy." in sections[1].text
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_chunker.py -v
```
Expected: `ModuleNotFoundError: No module named 'ingest.chunker'`.

**Step 3: Implement minimal code**
```python
# src/ingest/models.py — add
class Chunk(BaseModel):
    chunk_id: str
    chapter_number: int
    chapter_title: str
    section_title: str
    page_index_start: int
    page_index_end: int
    printed_page_label: str | None = None
    text: str
    figure_refs: list[FigureRef] = []
    token_count: int
    sequence: int
```

```python
# src/ingest/chunker.py
from dataclasses import dataclass, field

from ingest.headers import CHAPTER_HEADER_TEXT, FIGURE_CAPTION_PATTERN
from ingest.models import ChapterHeader, SubsectionHeader, TextSpan


@dataclass
class RawSection:
    chapter_number: int
    chapter_title: str
    section_title: str
    page_index_start: int
    page_index_end: int
    text: str = ""


def _chapter_for_page(chapters: list[ChapterHeader], page_index: int) -> ChapterHeader | None:
    applicable = [c for c in chapters if c.page_index <= page_index]
    return max(applicable, key=lambda c: c.page_index) if applicable else None


def group_into_sections(
    spans: list[TextSpan],
    chapters: list[ChapterHeader],
    subsections: list[SubsectionHeader],
) -> list[RawSection]:
    header_titles_by_page: dict[int, set[str]] = {}
    for h in subsections:
        header_titles_by_page.setdefault(h.page_index, set()).add(h.title)

    sections: list[RawSection] = []
    current: RawSection | None = None

    for span in spans:
        if CHAPTER_HEADER_TEXT.match(span.text) or FIGURE_CAPTION_PATTERN.match(span.text):
            continue
        is_header = span.text in header_titles_by_page.get(span.page_index, set())
        if is_header:
            chapter = _chapter_for_page(chapters, span.page_index)
            current = RawSection(
                chapter_number=chapter.chapter_number if chapter else 0,
                chapter_title=chapter.title if chapter else "",
                section_title=span.text,
                page_index_start=span.page_index,
                page_index_end=span.page_index,
            )
            sections.append(current)
        elif current is not None:
            current.text = f"{current.text} {span.text}".strip()
            current.page_index_end = span.page_index

    return sections
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_chunker.py -v
```
Expected: 1 passed.

**Step 5: Commit**
```bash
git add src/ingest/chunker.py src/ingest/models.py tests/ingest/test_chunker.py
git commit -m "[Feature] Ingest: group text spans into subsection-boundary sections"
```

### Chunk 1.9 — Sliding-window fallback for oversized sections

**Files**: Modify: `src/ingest/chunker.py` (add `apply_sliding_window`), `tests/ingest/test_chunker.py`.

**Step 1: Write failing test**
```python
# tests/ingest/test_chunker.py — add
from ingest.chunker import RawSection, apply_sliding_window


def test_short_section_is_not_split():
    section = RawSection(
        chapter_number=4,
        chapter_title="Energy Management",
        section_title="Total Energy",
        page_index_start=0,
        page_index_end=0,
        text="Short body text under the token limit.",
    )

    windows = apply_sliding_window(section, min_tokens=400, max_tokens=600, overlap_pct=0.15)

    assert len(windows) == 1
    assert windows[0] == section.text


def test_long_section_is_split_into_overlapping_windows():
    long_text = " ".join(f"word{i}" for i in range(1500))  # well over 600 tokens
    section = RawSection(
        chapter_number=4,
        chapter_title="Energy Management",
        section_title="Total Energy",
        page_index_start=0,
        page_index_end=5,
        text=long_text,
    )

    windows = apply_sliding_window(section, min_tokens=400, max_tokens=600, overlap_pct=0.15)

    assert len(windows) > 1
    # consecutive windows overlap: the tail of window N appears in the head of window N+1
    tail_words = windows[0].split()[-10:]
    assert any(w in windows[1] for w in tail_words)
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_chunker.py -v
```
Expected: `ImportError: cannot import name 'apply_sliding_window'`.

**Step 3: Implement minimal code**
```python
# src/ingest/chunker.py — add
from ingest.tokens import count_tokens


def apply_sliding_window(
    section: RawSection, min_tokens: int, max_tokens: int, overlap_pct: float
) -> list[str]:
    if count_tokens(section.text) <= max_tokens:
        return [section.text]

    words = section.text.split()
    target_words = max_tokens  # word count is an upper-bound proxy; count_tokens gates the real limit
    overlap_words = int(target_words * overlap_pct)
    step = target_words - overlap_words

    windows: list[str] = []
    start = 0
    while start < len(words):
        window_words = words[start : start + target_words]
        window_text = " ".join(window_words)
        windows.append(window_text)
        if start + target_words >= len(words):
            break
        start += step
    return windows
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_chunker.py -v
```
Expected: 3 passed.

**Step 5: Commit**
```bash
git add src/ingest/chunker.py tests/ingest/test_chunker.py
git commit -m "[Feature] Ingest: apply sliding-window fallback with overlap for oversized sections"
```

### Chunk 1.10 — End-to-end `chunk_pdf()` orchestrator

**Files**: Modify: `src/ingest/chunker.py` (add `chunk_pdf`), `tests/ingest/test_chunker.py`.

**Step 1: Write failing test**
```python
# tests/ingest/test_chunker.py — add
from ingest.chunker import chunk_pdf


def test_chunk_pdf_end_to_end_produces_stable_ids(make_pdf):
    pdf_path = make_pdf([
        [
            ("Chapter 4: Energy Management", 14, True),
            ("Total Energy", 10, True),
            ("Body text about total energy in the airplane.", 10, False),
        ],
        [
            ("Kinetic Energy", 10, True),
            ("Body text about kinetic energy during flight.", 10, False),
            ("Figure 4-1. Kinetic vs potential energy.", 9, False),
        ],
    ])

    chunks_run1 = chunk_pdf(pdf_path, min_tokens=400, max_tokens=600, overlap_pct=0.15)
    chunks_run2 = chunk_pdf(pdf_path, min_tokens=400, max_tokens=600, overlap_pct=0.15)

    assert len(chunks_run1) == 2
    assert [c.chunk_id for c in chunks_run1] == [c.chunk_id for c in chunks_run2]
    assert chunks_run1[0].chapter_number == 4
    assert chunks_run1[0].chapter_title == "Energy Management"
    assert chunks_run1[0].section_title == "Total Energy"
    assert chunks_run1[1].section_title == "Kinetic Energy"
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_chunker.py -v
```
Expected: `ImportError: cannot import name 'chunk_pdf'`.

**Step 3: Implement minimal code**
```python
# src/ingest/chunker.py — add
from pathlib import Path

from ingest.chunk_id import make_chunk_id
from ingest.figures import extract_figure_ref
from ingest.headers import detect_chapter_headers, detect_subsection_headers
from ingest.models import Chunk
from ingest.pdf_loader import extract_page_spans


def chunk_pdf(pdf_path: Path, min_tokens: int, max_tokens: int, overlap_pct: float) -> list[Chunk]:
    spans = extract_page_spans(pdf_path)
    chapters = detect_chapter_headers(spans)
    subsections = detect_subsection_headers(spans)
    sections = group_into_sections(spans, chapters, subsections)

    figure_refs_by_page: dict[int, list] = {}
    for span in spans:
        ref = extract_figure_ref(span.text)
        if ref:
            figure_refs_by_page.setdefault(span.page_index, []).append(ref)

    chunks: list[Chunk] = []
    for section in sections:
        windows = apply_sliding_window(section, min_tokens, max_tokens, overlap_pct)
        section_figure_refs = [
            ref
            for page in range(section.page_index_start, section.page_index_end + 1)
            for ref in figure_refs_by_page.get(page, [])
        ]
        for sequence, window_text in enumerate(windows):
            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(section.chapter_number, section.section_title, sequence),
                    chapter_number=section.chapter_number,
                    chapter_title=section.chapter_title,
                    section_title=section.section_title,
                    page_index_start=section.page_index_start,
                    page_index_end=section.page_index_end,
                    text=window_text,
                    figure_refs=section_figure_refs if sequence == 0 else [],
                    token_count=count_tokens(window_text),
                    sequence=sequence,
                )
            )
    return chunks
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_chunker.py -v
```
Expected: 4 passed.

**Step 5: Commit**
```bash
git add src/ingest/chunker.py tests/ingest/test_chunker.py
git commit -m "[Feature] Ingest: wire chunk_pdf end-to-end orchestrator with stable re-ingestion IDs"
```

**Note**: `printed_page_label` (Chunk 1.4's output) is deliberately not wired into `chunk_pdf` yet — it needs a page-footer-position heuristic this plan defers (see Technical Debt Strategy). `chunk_pdf` leaves it `None` for now; wiring it in is a follow-up chunk once the position heuristic exists.

### Chunk 1.11 — BM25 index build + search round-trip

**Files**: Create: `src/ingest/bm25_index.py`, `tests/ingest/test_bm25_index.py`.

**Step 1: Write failing test**
```python
# tests/ingest/test_bm25_index.py
from ingest.bm25_index import build_bm25_index, load_bm25_index, search_bm25
from ingest.models import Chunk


def _chunk(chunk_id, text):
    return Chunk(
        chunk_id=chunk_id,
        chapter_number=4,
        chapter_title="Energy Management",
        section_title="Total Energy",
        page_index_start=0,
        page_index_end=0,
        text=text,
        token_count=len(text.split()),
        sequence=0,
    )


def test_bm25_roundtrip_finds_expected_chunk(tmp_path):
    chunks = [
        _chunk("a", "Slow flight and stall speed procedures."),
        _chunk("b", "Crosswind takeoff and landing techniques."),
        _chunk("c", "Weight and balance calculations for the airplane."),
    ]
    index_dir = tmp_path / "bm25"
    build_bm25_index(chunks, index_dir)

    index, corpus_ids = load_bm25_index(index_dir)
    results = search_bm25(index, corpus_ids, "stall speed", top_k=1)

    assert results[0] == "a"
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_bm25_index.py -v
```
Expected: `ModuleNotFoundError: No module named 'ingest.bm25_index'`.

**Step 3: Implement minimal code**
```python
# src/ingest/bm25_index.py
import json
from pathlib import Path

import bm25s

from ingest.models import Chunk


def build_bm25_index(chunks: list[Chunk], index_dir: Path) -> None:
    corpus = [c.text for c in chunks]
    corpus_ids = [c.chunk_id for c in chunks]

    tokenized = bm25s.tokenize(corpus)
    index = bm25s.BM25()
    index.index(tokenized)

    index_dir.mkdir(parents=True, exist_ok=True)
    index.save(str(index_dir))
    (index_dir / "corpus_ids.json").write_text(json.dumps(corpus_ids))


def load_bm25_index(index_dir: Path) -> tuple[bm25s.BM25, list[str]]:
    index = bm25s.BM25.load(str(index_dir))
    corpus_ids = json.loads((index_dir / "corpus_ids.json").read_text())
    return index, corpus_ids


def search_bm25(index: bm25s.BM25, corpus_ids: list[str], query: str, top_k: int) -> list[str]:
    tokenized_query = bm25s.tokenize(query)
    positions, _scores = index.retrieve(tokenized_query, k=top_k)
    return [corpus_ids[i] for i in positions[0]]
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_bm25_index.py -v
```
Expected: 1 passed.

**Step 5: Commit**
```bash
git add src/ingest/bm25_index.py tests/ingest/test_bm25_index.py
git commit -m "[Feature] Ingest: build and query a bm25s sparse index over chunks"
```

### Chunk 1.12 — Vector index build + search round-trip (LanceDB + bge-small-en-v1.5)

**Files**: Create: `src/ingest/vector_index.py`, `tests/ingest/test_vector_index.py`.

**Step 1: Write failing test**
```python
# tests/ingest/test_vector_index.py
import pytest

from ingest.vector_index import build_vector_index, search_vector
from ingest.models import Chunk


def _chunk(chunk_id, text):
    return Chunk(
        chunk_id=chunk_id,
        chapter_number=4,
        chapter_title="Energy Management",
        section_title="Total Energy",
        page_index_start=0,
        page_index_end=0,
        text=text,
        token_count=len(text.split()),
        sequence=0,
    )


@pytest.mark.slow
def test_vector_search_finds_semantically_closest_chunk(tmp_path):
    chunks = [
        _chunk("a", "The stall occurs when the critical angle of attack is exceeded."),
        _chunk("b", "Weight and balance must be computed before every flight."),
        _chunk("c", "Radio communication procedures at towered airports."),
    ]
    db_path = tmp_path / "lancedb"

    build_vector_index(chunks, db_path)
    results = search_vector(db_path, "What causes an aerodynamic stall?", top_k=1)

    assert results[0] == "a"
```

**Step 2: Verify failure**
```bash
uv run pytest tests/ingest/test_vector_index.py -v -m slow
```
Expected: `ModuleNotFoundError: No module named 'ingest.vector_index'`.

**Step 3: Implement minimal code**
```python
# src/ingest/vector_index.py
from pathlib import Path

import lancedb
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME, device="cpu")
    return _model


def build_vector_index(chunks: list, db_path: Path) -> None:
    model = _get_model()
    embeddings = model.encode([c.text for c in chunks], normalize_embeddings=True)

    rows = [
        {
            "chunk_id": chunk.chunk_id,
            "text": chunk.text,
            "vector": embedding.tolist(),
        }
        for chunk, embedding in zip(chunks, embeddings)
    ]

    db = lancedb.connect(str(db_path))
    db.create_table("chunks", data=rows, mode="overwrite")


def search_vector(db_path: Path, query: str, top_k: int) -> list[str]:
    model = _get_model()
    query_vector = model.encode(query, normalize_embeddings=True).tolist()

    db = lancedb.connect(str(db_path))
    table = db.open_table("chunks")
    results = table.search(query_vector).limit(top_k).to_list()
    return [r["chunk_id"] for r in results]
```

Register the marker in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
markers = ["slow: local-model tests, skip with -m 'not slow' for the fast dev loop"]
```

**Step 4: Verify pass**
```bash
uv run pytest tests/ingest/test_vector_index.py -v -m slow
```
Expected: 1 passed (first run downloads `bge-small-en-v1.5`, ~130MB, one-time).

**Step 5: Commit**
```bash
git add src/ingest/vector_index.py tests/ingest/test_vector_index.py pyproject.toml
git commit -m "[Feature] Ingest: build and query a LanceDB vector index using bge-small-en-v1.5"
```

### Chunk 1.13 — `ingest` CLI command

**Files**: Create: `src/app/main.py`, `src/app/__init__.py`, `tests/app/test_ingest_command.py`.

**Step 1: Write failing test**
```python
# tests/app/test_ingest_command.py
from typer.testing import CliRunner

from app.main import app

runner = CliRunner()


def test_ingest_command_creates_both_indexes(make_pdf, tmp_path):
    pdf_path = make_pdf([[
        ("Chapter 4: Energy Management", 14, True),
        ("Total Energy", 10, True),
        ("Body text about total energy in the airplane during flight.", 10, False),
    ]])
    out_dir = tmp_path / "out"

    result = runner.invoke(app, ["ingest", "--pdf", str(pdf_path), "--out", str(out_dir)])

    assert result.exit_code == 0
    assert (out_dir / "bm25").exists()
    assert (out_dir / "lancedb").exists()
```

`make_pdf` needs to be visible to `tests/app/` too — move the fixture from `tests/ingest/conftest.py` to a shared `tests/conftest.py`.

**Step 2: Verify failure**
```bash
uv run pytest tests/app/test_ingest_command.py -v -m slow
```
Expected: `ModuleNotFoundError: No module named 'app.main'`.

**Step 3: Implement minimal code**
```python
# src/app/main.py
from pathlib import Path

import typer

from config import get_settings
from ingest.bm25_index import build_bm25_index
from ingest.chunker import chunk_pdf
from ingest.vector_index import build_vector_index

app = typer.Typer()


@app.command()
def ingest(pdf: Path, out: Path):
    settings = get_settings()
    chunks = chunk_pdf(
        pdf,
        min_tokens=settings.chunking.min_tokens,
        max_tokens=settings.chunking.max_tokens,
        overlap_pct=settings.chunking.overlap_pct,
    )
    build_bm25_index(chunks, out / "bm25")
    build_vector_index(chunks, out / "lancedb")
    typer.echo(f"Ingested {len(chunks)} chunks from {pdf} into {out}")


if __name__ == "__main__":
    app()
```

**Step 4: Verify pass**
```bash
uv run pytest tests/app/test_ingest_command.py -v -m slow
```
Expected: 1 passed.

**Step 5: Commit**
```bash
git add src/app tests/app tests/conftest.py
git rm tests/ingest/conftest.py 2>/dev/null || true
git commit -m "[Feature] CLI: add typer ingest command wiring chunk_pdf into both indexes"
```

### Chunk 1.14 — Full pipeline run against the real handbook (manual verification, not unit-tested)

Not a TDD chunk — this is the manual spot-check the design doc calls for before trusting the chunker on the real document.

**Steps**:
1. `uv run python -m app.main ingest --pdf "Airplane Flying Handbook (FAA-H-8083-3C).pdf" --out data/index`
2. Manually inspect: chunk count, a sample of `chapter_title`/`section_title` pairs for correctness, table-heavy pages (weight-and-balance, V-speed reference tables — flagged as a real risk in the design doc) for garbled extraction, and `SIZE_RATIO_THRESHOLD` (Chunk 1.3) against real observed font sizes.
3. Log findings to `.agent/decisions.log` (tune `SIZE_RATIO_THRESHOLD` if needed) and `PROJECT_HISTORY.md`.
4. If subsection/table extraction is materially wrong, that's a new RED test against a synthetic fixture reproducing the failure — not a manual patch.

---

## Technical Debt Strategy

Explicit shortcuts taken in this plan, to be added to a `BUGS.md`/backlog if not addressed immediately after Block 1 lands:

1. **`SIZE_RATIO_THRESHOLD = 1.15`** (Chunk 1.3) is an untuned guess. Must be validated against the real handbook's actual font-size distribution (Chunk 1.14) before trusting subsection detection on the full corpus.
2. **`classify_page_label`** (Chunk 1.4) matches on text shape only, not footer position — not yet wired into `chunk_pdf`'s `printed_page_label` field. Needs a bbox-based "is this near the bottom of the page" check before it's trustworthy enough to surface in citations.
3. **Table extraction is unhandled** — the design doc flags zero `Table N-N.` caption matches found anywhere in the corpus. This plan does not add any table-specific handling; Chunk 1.14's manual spot-check is the first real signal on whether this is a problem, and a fix (if needed) is out of scope for Block 1.
4. **`tiktoken`** was added mid-plan (Chunk 1.7) as a dependency not in the original design doc's library table — needs a `.agent/decisions.log` entry at build time, not just this plan note.
5. **Sliding-window word-count proxy** (Chunk 1.9): windows are cut on word boundaries sized to `max_tokens` as a word-count proxy, not on an exact token boundary — `count_tokens` gates whether windowing triggers at all, but doesn't guarantee every individual window lands inside `[min_tokens, max_tokens]` precisely. Acceptable approximation for a first pass; revisit if Chunk 1.14's spot-check shows windows are frequently far outside the target range.

## Production & Design Standards (adapted — no frontend in this project)

- **Timeout Mapping**: N/A for Block 1 (no network calls). Anthropic API timeouts belong to Block 4 (generation) — flagged there, not here.
- **Error Handling**: `chunk_pdf` and index builders currently let exceptions propagate (fail loudly on malformed PDFs) rather than swallowing errors — appropriate for an offline, human-supervised ingestion run. Revisit only if ingestion needs to run unattended in CI.
- **Loading States**: N/A (no UI).
- **Live-Service Test Gate**: no Block 1 test calls a paid API. Chunk 1.12's local-model test is marked `@pytest.mark.slow`, not gated behind an env flag, since it costs nothing and runs offline after first model download.

---

## Remaining Blocks (to be detailed later via follow-up `/plan` passes)

Sketched now so the roadmap is visible; **not** built out to RED/GREEN-code detail yet, per this plan's stated scope.

### Block 2: Hybrid Retrieval
- Success criteria: BM25 search wrapper and vector search wrapper both usable standalone; RRF fusion combines both rankings with configurable weights (`settings.retrieval`); disabling one retriever or reweighting visibly changes top-N (design doc acceptance criterion).
- Chunks (sketch): `retrieval/bm25.py` search wrapper over Block 1's index · `retrieval/vector.py` search wrapper over Block 1's index · `retrieval/fusion.py` RRF combine with `rrf_k`/`bm25_weight`/`vector_weight` from config · fusion integration test proving weight changes reorder results.

### Block 3: Cross-Encoder Reranking
- Success criteria: reranker reorders fused top-N to top-k; model swappable via `settings.rerank.model` without code changes; disabling rerank (`settings.rerank.enabled=False`) is a no-op passthrough.
- Chunks (sketch): `rerank/cross_encoder.py` wrapper around `sentence_transformers.CrossEncoder` · config-driven top-k truncation · enabled/disabled passthrough test.

### Block 4: Grounded Generation
- Success criteria: prompt instructs "answer only from provided context, cite by chunk_id"; insufficient context yields an explicit "I don't have that" rather than a hallucinated answer; bounded retry (3 attempts, backoff) on Anthropic API errors.
- Chunks (sketch): versioned prompt template under `prompts/` · `generate/client.py` Anthropic call wrapper with retry/backoff · structured `{answer_text, citations: [chunk_id]}` output parsing · insufficient-context test case.
- **Timeout Mapping** (owed here, not Block 1): every Anthropic API call needs an explicit timeout — 30s per the "heavy AI operation" guidance in `.agent/workflows/plan.md`.

### Block 5: Citation Verification
- Success criteria: each cited claim is checked against its source chunk (LLM-judge or NLI-style); unsupported citations are stripped, not silently kept; `coverage` score computed and a response is flagged `low_confidence` below `settings.citations.low_confidence_threshold`.
- Chunks (sketch): `citations/verify.py` per-claim faithfulness check · coverage scoring · low-confidence flagging integration test.

### Block 6: Evaluation Harness
- Success criteria: golden dataset schema distinguishes `auto_generated` vs `reviewed`; retrieval metrics (Recall@k, MRR, nDCG) are pure-CPU and deterministic; answer-quality judges run at `judge_temperature=0` via Haiku; local response cache keyed on `(question, config_hash)` avoids re-spending on unchanged inputs during eval-harness debugging; CI gate uses tolerance bands, not hard cutoffs, for judge-based metrics.
- Chunks (sketch): golden dataset pydantic schema + the 8 confirmed sample questions from the design doc · retrieval metrics module · LLM-judge module (Haiku, temp 0) · response cache · baseline storage keyed on git commit + prompt version.

### Block 7: Observability
- Success criteria: `Tracer` protocol with a `LangfuseTracer` implementation; every pipeline stage (bm25, vector, fusion, rerank, generate, verify) is a traced span; cost calculator from token usage × price table; daily running cost total surfaced, not just per-request.
- Chunks (sketch): `observability/tracer.py` protocol · `observability/langfuse_tracer.py` impl · cost calculator · daily cost aggregation · span wiring through the query-time pipeline built in Blocks 2–5.

### Block 8: CLI Completion + CI
- Success criteria: `query`, `eval`, `serve` (stretch) CLI commands complete the `app/main.py` surface; `cheap-gate.yml` runs retrieval metrics on every push and fails below threshold vs. baseline; `nightly-eval.yml` runs expensive judge metrics on a schedule/manual trigger only; CI summary shows metrics vs. baseline pass/fail per metric.
- Chunks (sketch): `query`/`eval` typer commands · `.github/workflows/cheap-gate.yml` · `.github/workflows/nightly-eval.yml` · a deliberately-bad-config test proving the gate actually fails.

### Block 9: Portfolio Deliverables
- Success criteria: README with architecture diagram, hybrid retrieval/reranking/verification explanation, observability section with trace screenshots; eval report showing baseline metrics and a caught regression example.
- Chunks (sketch): architecture diagram · README · eval report generation from a stored baseline run + one deliberately regressed run.

---

## Persistence & Next Step

Saved to `docs/plans/2026-07-11-ask-my-docs-implementation-plan.md`.

**Ready to start building? Use `/build`.**
