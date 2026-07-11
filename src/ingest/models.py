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
