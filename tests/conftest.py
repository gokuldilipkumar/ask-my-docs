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
