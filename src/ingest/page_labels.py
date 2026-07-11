import re

ROMAN_PATTERN = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
CHAPTER_RELATIVE_PATTERN = re.compile(r"^\d+-\d+$")


def classify_page_label(text: str) -> str | None:
    if ROMAN_PATTERN.match(text) or CHAPTER_RELATIVE_PATTERN.match(text):
        return text
    return None
