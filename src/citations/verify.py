from citations.schema import VerifiedAnswer
from config.settings import CitationConfig
from generate.schema import GeneratedAnswer


def verify_citations(
    client,
    question: str,
    answer: GeneratedAnswer,
    chunk_texts: dict[str, str],
    config: CitationConfig,
) -> VerifiedAnswer:
    if not answer.citations:
        return VerifiedAnswer(
            answer_text=answer.answer_text, citations=[], coverage=1.0, low_confidence=False
        )
    raise NotImplementedError  # real judge call lands in Chunk 5.3
