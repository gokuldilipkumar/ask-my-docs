from pathlib import Path

import fitz
import pytest


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
