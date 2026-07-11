from ingest.pdf_loader import extract_page_spans
from ingest.headers import detect_chapter_headers, detect_subsection_headers
from ingest.chunker import RawSection, apply_sliding_window, group_into_sections


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


def test_short_section_is_not_split():
    section = RawSection(
        chapter_number=4,
        chapter_title="Energy Management",
        section_title="Total Energy",
        page_index_start=0,
        page_index_end=0,
        text="Short body text under the token limit.",
    )

    windows = apply_sliding_window(section, min_tokens=400, max_tokens=600, overlap_pct=0.15)

    assert len(windows) == 1
    assert windows[0] == section.text


def test_long_section_is_split_into_overlapping_windows():
    long_text = " ".join(f"word{i}" for i in range(1500))  # well over 600 tokens
    section = RawSection(
        chapter_number=4,
        chapter_title="Energy Management",
        section_title="Total Energy",
        page_index_start=0,
        page_index_end=5,
        text=long_text,
    )

    windows = apply_sliding_window(section, min_tokens=400, max_tokens=600, overlap_pct=0.15)

    assert len(windows) > 1
    # consecutive windows overlap: the tail of window N appears in the head of window N+1
    tail_words = windows[0].split()[-10:]
    assert any(w in windows[1] for w in tail_words)
