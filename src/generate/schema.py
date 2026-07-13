from pydantic import BaseModel


class GeneratedAnswer(BaseModel):
    answer_text: str
    citations: list[str]
