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
