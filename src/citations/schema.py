from pydantic import BaseModel


class CitationVerdict(BaseModel):
    chunk_id: str
    supported: bool


class VerificationResult(BaseModel):
    verdicts: list[CitationVerdict]


class VerifiedAnswer(BaseModel):
    answer_text: str
    citations: list[str]
    coverage: float
    low_confidence: bool
