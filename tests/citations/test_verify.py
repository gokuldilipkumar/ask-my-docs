import pytest

from citations.schema import VerifiedAnswer
from citations.verify import verify_citations
from config.settings import CitationConfig
from generate.schema import GeneratedAnswer


def test_no_citations_returns_full_coverage_without_calling_client():
    class ExplodingClient:
        def __getattr__(self, name):
            pytest.fail("must not touch the Anthropic client when there are no citations")

    answer = GeneratedAnswer(answer_text="I don't have information about that.", citations=[])
    config = CitationConfig()

    result = verify_citations(ExplodingClient(), "any question", answer, {}, config)

    assert isinstance(result, VerifiedAnswer)
    assert result.citations == []
    assert result.coverage == 1.0
    assert result.low_confidence is False
