from dataclasses import dataclass

from ingest.headers import CHAPTER_PATTERN, FIGURE_CAPTION_PATTERN
from ingest.models import ChapterHeader, SubsectionHeader, TextSpan


@dataclass
class RawSection:
    chapter_number: int
    chapter_title: str
    section_title: str
    page_index_start: int
    page_index_end: int
    text: str = ""


def _chapter_for_page(chapters: list[ChapterHeader], page_index: int) -> ChapterHeader | None:
    applicable = [c for c in chapters if c.page_index <= page_index]
    return max(applicable, key=lambda c: c.page_index) if applicable else None


def group_into_sections(
    spans: list[TextSpan],
    chapters: list[ChapterHeader],
    subsections: list[SubsectionHeader],
) -> list[RawSection]:
    header_titles_by_page: dict[int, set[str]] = {}
    for h in subsections:
        header_titles_by_page.setdefault(h.page_index, set()).add(h.title)

    sections: list[RawSection] = []
    current: RawSection | None = None

    for span in spans:
        if CHAPTER_PATTERN.match(span.text) or FIGURE_CAPTION_PATTERN.match(span.text):
            continue
        is_header = span.text in header_titles_by_page.get(span.page_index, set())
        if is_header:
            chapter = _chapter_for_page(chapters, span.page_index)
            current = RawSection(
                chapter_number=chapter.chapter_number if chapter else 0,
                chapter_title=chapter.title if chapter else "",
                section_title=span.text,
                page_index_start=span.page_index,
                page_index_end=span.page_index,
            )
            sections.append(current)
        elif current is not None:
            current.text = f"{current.text} {span.text}".strip()
            current.page_index_end = span.page_index

    return sections
