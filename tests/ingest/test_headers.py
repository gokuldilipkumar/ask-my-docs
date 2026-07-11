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
