from ingest.page_labels import classify_page_label


def test_classifies_roman_numeral_front_matter_label():
    assert classify_page_label("iii") == "iii"
    assert classify_page_label("xiv") == "xiv"


def test_classifies_chapter_relative_body_label():
    assert classify_page_label("4-1") == "4-1"
    assert classify_page_label("12-23") == "12-23"


def test_returns_none_for_unrelated_text():
    assert classify_page_label("Total Energy") is None
    assert classify_page_label("Chapter 4: Energy Management") is None
