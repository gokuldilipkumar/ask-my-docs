from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ingest.chunk_id import make_chunk_id
from ingest.figures import extract_figure_ref
from ingest.headers import (
    CHAPTER_PATTERN,
    FIGURE_CAPTION_PATTERN,
    detect_chapter_headers,
    detect_subsection_headers,
)
from ingest.models import Chunk, ChapterHeader, FigureRef, SubsectionHeader, TextSpan
from ingest.pdf_loader import extract_page_spans
from ingest.tokens import count_tokens


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
    # Match header spans by full font signature, not text alone: body spans can
    # share a header's text (glossary V-speed notation leaves stray "V" spans on
    # a page whose alphabet heading is "V") but not its size/boldness.
    header_keys_by_page: dict[int, set[tuple[str, float, bool]]] = {}
    for h in subsections:
        header_keys_by_page.setdefault(h.page_index, set()).add(
            (h.title, h.font_size, h.is_bold)
        )

    sections: list[RawSection] = []
    current: RawSection | None = None

    for span in spans:
        if CHAPTER_PATTERN.match(span.text) or FIGURE_CAPTION_PATTERN.match(span.text):
            continue
        is_header = (span.text, span.font_size, span.is_bold) in header_keys_by_page.get(
            span.page_index, set()
        )
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


def apply_sliding_window(
    section: RawSection, min_tokens: int, max_tokens: int, overlap_pct: float
) -> list[str]:
    if count_tokens(section.text) <= max_tokens:
        return [section.text]

    words = section.text.split()
    # Approximation: windows are sized in words, but a word is >= 1 token, so a
    # max_tokens-word window usually *exceeds* max_tokens tokens. Token-accurate
    # windowing is open debt in BUGS.md.
    target_words = max_tokens
    overlap_words = int(target_words * overlap_pct)
    step = target_words - overlap_words

    starts: list[int] = []
    start = 0
    while start < len(words):
        starts.append(start)
        if start + target_words >= len(words):
            break
        start += step

    windows = [" ".join(words[s : s + target_words]) for s in starts]

    # A trailing window under min_tokens is an orphan fragment, not a usable chunk -
    # fold it back into the previous window instead of emitting it standalone.
    if len(windows) > 1 and count_tokens(windows[-1]) < min_tokens:
        merged_text = " ".join(words[starts[-2] :])
        windows = windows[:-2] + [merged_text]

    return windows


def chunk_pdf(
    pdf_path: Path,
    min_tokens: int,
    max_tokens: int,
    overlap_pct: float,
    body_page_start: int = 0,
    body_page_end: int | None = None,
) -> list[Chunk]:
    spans = extract_page_spans(pdf_path)
    # Drop front/back matter before header detection: TOC pages repeat chapter-header
    # lines verbatim (duplicating every detected chapter) and index/glossary headings
    # otherwise fragment into hundreds of junk sections.
    spans = [
        s
        for s in spans
        if s.page_index >= body_page_start
        and (body_page_end is None or s.page_index <= body_page_end)
    ]
    chapters = detect_chapter_headers(spans)
    subsections = detect_subsection_headers(spans)
    sections = group_into_sections(spans, chapters, subsections)

    figure_refs_by_page: dict[int, list[FigureRef]] = {}
    for span in spans:
        ref = extract_figure_ref(span.text)
        if ref:
            figure_refs_by_page.setdefault(span.page_index, []).append(ref)

    chunks: list[Chunk] = []
    for section in sections:
        windows = apply_sliding_window(section, min_tokens, max_tokens, overlap_pct)
        section_figure_refs = [
            ref
            for page in range(section.page_index_start, section.page_index_end + 1)
            for ref in figure_refs_by_page.get(page, [])
        ]
        for sequence, window_text in enumerate(windows):
            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(
                        section.chapter_number,
                        section.section_title,
                        section.page_index_start,
                        sequence,
                    ),
                    chapter_number=section.chapter_number,
                    chapter_title=section.chapter_title,
                    section_title=section.section_title,
                    page_index_start=section.page_index_start,
                    page_index_end=section.page_index_end,
                    text=window_text,
                    # attach figure refs once per section, not per window, so
                    # overlapping windows don't each re-list the same figures
                    figure_refs=section_figure_refs if sequence == 0 else [],
                    token_count=count_tokens(window_text),
                    sequence=sequence,
                )
            )
    # Unique ids are a designed invariant that citations and eval references
    # depend on — count it here rather than assume the hash scheme guarantees it
    # (identically-titled sections starting on the same page would still collide).
    id_counts = Counter(c.chunk_id for c in chunks)
    collisions = {cid: n for cid, n in id_counts.items() if n > 1}
    if collisions:
        raise ValueError(f"chunk_id collisions: {collisions}")
    return chunks
