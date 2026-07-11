from ingest.pdf_loader import extract_page_spans
from ingest.headers import detect_chapter_headers, detect_subsection_headers


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
        ("More body text about the topic.", 10, False),
        ("Even more body text here.", 10, False),
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


def test_does_not_flag_inline_bold_emphasis_sharing_a_line_as_header(make_pdf):
    # Reproduces a real-corpus failure: "Rule #1:" is bolded inline within a
    # sentence, not a standalone heading on its own line.
    pdf_path = make_pdf([[
        ("Chapter 4: Energy Management", 14, True),
        [("Rule #1:", 10, True), ("If you want to move to a new energy state, then:", 10, False)],
        ("Body text explaining the rule in more detail.", 10, False),
        ("Total Energy", 10, True),
        ("Body text about total energy.", 10, False),
    ]])
    spans = extract_page_spans(pdf_path)

    subsections = detect_subsection_headers(spans)

    assert [s.title for s in subsections] == ["Total Energy"]
