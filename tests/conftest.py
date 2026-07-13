import os
from pathlib import Path

import fitz
import pytest

from ingest.models import Chunk


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_LIVE_API_TESTS") == "1":
        return
    skip_live = pytest.mark.skip(reason="set RUN_LIVE_API_TESTS=1 to run tests that call the real Anthropic API")
    for item in items:
        if "live_api" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def make_chunk():
    def _make_chunk(chunk_id: str, text: str) -> Chunk:
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

    return _make_chunk


@pytest.fixture
def make_pdf(tmp_path):
    def _make_pdf(pages: list[list[tuple | list[tuple]]]) -> Path:
        """pages: list of pages; each page is a list of rows.

        A row is either a single (text, font_size, bold) tuple (its own line),
        or a list of such tuples placed side-by-side on one shared line
        (simulates inline bold emphasis within a paragraph).
        """
        doc = fitz.open()
        for rows in pages:
            page = doc.new_page()
            y = 72
            max_size = 10
            for row in rows:
                runs = [row] if isinstance(row, tuple) else row
                x = 72
                for text, size, bold in runs:
                    fontname = "hebo" if bold else "helv"
                    page.insert_text((x, y), text, fontsize=size, fontname=fontname)
                    x += fitz.get_text_length(text, fontname=fontname, fontsize=size) + 5
                max_size = max(r[1] for r in runs)
                y += max_size + 10
        path = tmp_path / "test.pdf"
        doc.save(path)
        doc.close()
        return path

    return _make_pdf
