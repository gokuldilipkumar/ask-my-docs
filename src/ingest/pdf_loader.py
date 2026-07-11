from pathlib import Path

import fitz

from ingest.models import TextSpan

BOLD_FLAG = 1 << 4  # PyMuPDF span flag bit for bold

# A span is a subscript continuation of the previous span on its line when it is
# much smaller, starts where the previous span ends, and sits below its top edge
# (the handbook typesets V-speeds as "V" + a 0.66x-size subscript like "MC").
# PyMuPDF's superscript flag is NOT set on these spans, so geometry is the only signal.
SUBSCRIPT_SIZE_RATIO = 0.8
SUBSCRIPT_MAX_X_GAP = 1.0


def _is_subscript_of(prev: dict, span: dict) -> bool:
    return (
        span["size"] < prev["size"] * SUBSCRIPT_SIZE_RATIO
        and 0 <= span["bbox"][0] - prev["bbox"][2] <= SUBSCRIPT_MAX_X_GAP
        and span["bbox"][1] > prev["bbox"][1]
    )


def _join_subscript_spans(line_spans: list[dict]) -> list[dict]:
    joined: list[dict] = []
    for span in line_spans:
        if joined and _is_subscript_of(joined[-1], span):
            prev = joined[-1]
            prev["text"] = prev["text"].rstrip() + span["text"].strip()
            prev["bbox"] = (
                prev["bbox"][0],
                min(prev["bbox"][1], span["bbox"][1]),
                span["bbox"][2],
                max(prev["bbox"][3], span["bbox"][3]),
            )
        else:
            joined.append(dict(span))
    return joined


def extract_page_spans(pdf_path: Path) -> list[TextSpan]:
    doc = fitz.open(pdf_path)
    spans: list[TextSpan] = []
    for page_index, page in enumerate(doc):
        raw = page.get_text("dict")
        for block in raw["blocks"]:
            for line in block.get("lines", []):
                non_empty_spans = [s for s in line["spans"] if s["text"].strip()]
                non_empty_spans = _join_subscript_spans(non_empty_spans)
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
