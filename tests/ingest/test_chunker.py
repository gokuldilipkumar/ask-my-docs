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
