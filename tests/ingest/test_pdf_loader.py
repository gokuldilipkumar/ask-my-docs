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
