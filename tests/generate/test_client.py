import pytest

from config.settings import GenerationConfig
from generate.client import generate_answer
from generate.schema import GeneratedAnswer


def test_empty_chunks_returns_canned_answer_without_calling_client():
    class ExplodingClient:
        def __getattr__(self, name):
            pytest.fail("must not touch the Anthropic client when there are no chunks")

    config = GenerationConfig()

    result = generate_answer(ExplodingClient(), "any question", [], config)

    assert isinstance(result, GeneratedAnswer)
    assert result.citations == []
    assert "don't have" in result.answer_text.lower()
