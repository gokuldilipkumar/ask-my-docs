import fitz

from ingest.pdf_loader import extract_page_spans


def _make_subscript_pdf(tmp_path):
    """One line typeset like the handbook's V-speeds: a full-size base span,
    an x-adjacent smaller span shifted below the baseline (the subscript),
    then a full-size continuation span."""
    doc = fitz.open()
    page = doc.new_page()
    x, y = 72, 100
    page.insert_text((x, y), "The demonstration of V", fontsize=10, fontname="helv")
    w = fitz.get_text_length("The demonstration of V", fontname="helv", fontsize=10)
    page.insert_text((x + w, y + 2.5), "MC", fontsize=6.6, fontname="helv")
    w2 = fitz.get_text_length("MC", fontname="helv", fontsize=6.6)
    page.insert_text((x + w + w2 + 2, y), "requires care.", fontsize=10, fontname="helv")
    path = tmp_path / "subscript.pdf"
    doc.save(path)
    doc.close()
    return path


def test_joins_subscript_span_to_its_base_span(tmp_path):
    pdf_path = _make_subscript_pdf(tmp_path)

    spans = extract_page_spans(pdf_path)

    assert [s.text for s in spans] == ["The demonstration of VMC", "requires care."]
    # the merged span keeps the base font, and both spans see the post-merge line width
    assert spans[0].font_size == 10
    assert all(s.line_span_count == 2 for s in spans)


def test_does_not_join_same_size_adjacent_spans(make_pdf):
    # sanity: ordinary side-by-side same-size runs stay separate spans
    pdf_path = make_pdf([[
        [("plain text", 10, False), ("bold label", 10, True)],
    ]])

    spans = extract_page_spans(pdf_path)

    assert [s.text for s in spans] == ["plain text", "bold label"]


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
