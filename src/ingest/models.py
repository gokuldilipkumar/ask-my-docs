from pydantic import BaseModel


class TextSpan(BaseModel):
    text: str
    font_size: float
    is_bold: bool
    page_index: int
    bbox: tuple[float, float, float, float]


class ChapterHeader(BaseModel):
    chapter_number: int
    title: str
    page_index: int


class SubsectionHeader(BaseModel):
    title: str
    page_index: int
    font_size: float
    is_bold: bool


class FigureRef(BaseModel):
    figure_number: str
    caption: str


class Chunk(BaseModel):
    chunk_id: str
    chapter_number: int
    chapter_title: str
    section_title: str
    page_index_start: int
    page_index_end: int
    printed_page_label: str | None = None
    text: str
    figure_refs: list[FigureRef] = []
    token_count: int
    sequence: int
