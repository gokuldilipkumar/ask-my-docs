from pydantic import BaseModel


class TextSpan(BaseModel):
    text: str
    font_size: float
    is_bold: bool
    page_index: int
    bbox: tuple[float, float, float, float]
