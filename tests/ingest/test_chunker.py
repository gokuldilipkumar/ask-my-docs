import pytest

from ingest.pdf_loader import extract_page_spans
from ingest.headers import detect_chapter_headers, detect_subsection_headers
from ingest.chunker import RawSection, apply_sliding_window, chunk_pdf, group_into_sections


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


def test_trailing_short_window_is_merged_into_previous_window():
    # 650 words leaves a ~140-word remainder after the first 600-word window,
    # which is well under min_tokens=400 and must not survive as an orphan chunk.
    words = [f"word{i}" for i in range(650)]
    text = " ".join(words)
    section = RawSection(
        chapter_number=4,
        chapter_title="Energy Management",
        section_title="Total Energy",
        page_index_start=0,
        page_index_end=5,
        text=text,
    )

    windows = apply_sliding_window(section, min_tokens=400, max_tokens=600, overlap_pct=0.15)

    assert len(windows) == 1
    assert windows[0] == text


def test_body_page_range_filters_front_and_back_matter(make_pdf):
    pdf_path = make_pdf([
        [   # front matter: TOC page repeating the chapter-header line verbatim
            ("Chapter 4: Energy Management", 14, True),
            ("Total Energy 4-1", 10, False),
        ],
        [   # body
            ("Chapter 4: Energy Management", 14, True),
            ("Total Energy", 10, True),
            ("Body text about total energy.", 10, False),
        ],
        [   # back matter: index page
            ("Index", 14, True),
            ("stall 4-2, 4-3, 5-1", 10, False),
        ],
    ])

    chunks = chunk_pdf(
        pdf_path,
        min_tokens=400,
        max_tokens=600,
        overlap_pct=0.15,
        body_page_start=1,
        body_page_end=1,
    )

    assert [c.section_title for c in chunks] == ["Total Energy"]
    assert chunks[0].chapter_number == 4
    assert "Body text about total energy." in chunks[0].text
    assert "stall 4-2" not in chunks[0].text


def test_chunk_pdf_end_to_end_produces_stable_ids(make_pdf):
    pdf_path = make_pdf([
        [
            ("Chapter 4: Energy Management", 14, True),
            ("Total Energy", 10, True),
            ("Body text about total energy in the airplane.", 10, False),
        ],
        [
            ("Kinetic Energy", 10, True),
            ("Body text about kinetic energy during flight.", 10, False),
            ("Figure 4-1. Kinetic vs potential energy.", 9, False),
        ],
    ])

    chunks_run1 = chunk_pdf(pdf_path, min_tokens=400, max_tokens=600, overlap_pct=0.15)
    chunks_run2 = chunk_pdf(pdf_path, min_tokens=400, max_tokens=600, overlap_pct=0.15)

    assert len(chunks_run1) == 2
    assert [c.chunk_id for c in chunks_run1] == [c.chunk_id for c in chunks_run2]
    assert chunks_run1[0].chapter_number == 4
    assert chunks_run1[0].chapter_title == "Energy Management"
    assert chunks_run1[0].section_title == "Total Energy"
    assert chunks_run1[1].section_title == "Kinetic Energy"


def test_repeated_section_title_across_pages_yields_unique_chunk_ids(make_pdf):
    # the real handbook repeats titles like "Common Errors" once per maneuver
    # within a chapter; their chunks must not share ids
    pdf_path = make_pdf([
        [
            ("Chapter 5: Maneuvers", 14, True),
            ("Common Errors", 10, True),
            ("Body text about slow flight errors.", 10, False),
        ],
        [
            ("Common Errors", 10, True),
            ("Body text about stall recovery errors.", 10, False),
        ],
    ])

    chunks = chunk_pdf(pdf_path, min_tokens=400, max_tokens=600, overlap_pct=0.15)

    ids = [c.chunk_id for c in chunks]
    assert len(chunks) == 2
    assert len(set(ids)) == len(ids)


def test_chunk_pdf_fails_loud_on_chunk_id_collision(make_pdf):
    # two identically-titled sections starting on the same page still collide
    # (page_index_start can't tell them apart) — refuse to build a corpus with
    # ambiguous ids rather than silently shipping it
    pdf_path = make_pdf([[
        ("Chapter 5: Maneuvers", 14, True),
        ("Common Errors", 10, True),
        ("Body text one.", 10, False),
        ("Common Errors", 10, True),
        ("Body text two.", 10, False),
    ]])

    with pytest.raises(ValueError, match="collision"):
        chunk_pdf(pdf_path, min_tokens=400, max_tokens=600, overlap_pct=0.15)
