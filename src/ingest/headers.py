import re
from collections import Counter

from ingest.models import ChapterHeader, SubsectionHeader, TextSpan

CHAPTER_PATTERN = re.compile(r"^Chapter (\d+): (.+)$")
FIGURE_CAPTION_PATTERN = re.compile(r"^Figure \d+-\d+\.")
SIZE_RATIO_THRESHOLD = 1.15


def detect_chapter_headers(spans: list[TextSpan]) -> list[ChapterHeader]:
    headers = []
    for span in spans:
        match = CHAPTER_PATTERN.match(span.text)
        if match:
            headers.append(
                ChapterHeader(
                    chapter_number=int(match.group(1)),
                    title=match.group(2),
                    page_index=span.page_index,
                )
            )
    return headers


def detect_subsection_headers(spans: list[TextSpan]) -> list[SubsectionHeader]:
    by_page: dict[int, list[TextSpan]] = {}
    for span in spans:
        by_page.setdefault(span.page_index, []).append(span)

    headers: list[SubsectionHeader] = []
    for page_index, page_spans in by_page.items():
        candidates = [
            s
            for s in page_spans
            if not CHAPTER_PATTERN.match(s.text) and not FIGURE_CAPTION_PATTERN.match(s.text)
        ]
        if not candidates:
            continue

        body_size = Counter(s.font_size for s in candidates).most_common(1)[0][0]

        for span in candidates:
            if span.font_size == body_size and not span.is_bold:
                continue  # body-sized, non-bold text is never a header
            if span.is_bold or span.font_size > body_size * SIZE_RATIO_THRESHOLD:
                headers.append(
                    SubsectionHeader(
                        title=span.text,
                        page_index=page_index,
                        font_size=span.font_size,
                        is_bold=span.is_bold,
                    )
                )
    return headers
