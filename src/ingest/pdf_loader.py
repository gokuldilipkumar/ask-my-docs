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
                non_empty_spans = [s for s in line["spans"] if s["text"].strip()]
                for span in non_empty_spans:
                    spans.append(
                        TextSpan(
                            text=span["text"].strip(),
                            font_size=span["size"],
                            is_bold=bool(span["flags"] & BOLD_FLAG),
                            page_index=page_index,
                            bbox=tuple(span["bbox"]),
                            line_span_count=len(non_empty_spans),
                        )
                    )
    doc.close()
    return spans
