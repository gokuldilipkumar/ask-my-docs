import re

from ingest.models import ChapterHeader, TextSpan

CHAPTER_PATTERN = re.compile(r"^Chapter (\d+): (.+)$")


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
