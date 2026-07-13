import anthropic
import pytest

from config.settings import GenerationConfig, Settings
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


def test_generate_answer_configures_client_with_retry_and_timeout():
    canned = GeneratedAnswer(answer_text="Stalls happen when...", citations=["abc123"])

    class FakeMessages:
        def __init__(self):
            self.parse_kwargs = None

        def parse(self, **kwargs):
            self.parse_kwargs = kwargs

            class FakeResponse:
                parsed_output = canned

            return FakeResponse()

    class FakeScopedClient:
        def __init__(self):
            self.messages = FakeMessages()

    class FakeClient:
        def __init__(self):
            self.with_options_kwargs = None
            self.scoped = FakeScopedClient()

        def with_options(self, **kwargs):
            self.with_options_kwargs = kwargs
            return self.scoped

    client = FakeClient()
    config = GenerationConfig(model="claude-sonnet-5", max_tokens=999, max_retries=7, timeout_seconds=12.0)

    result = generate_answer(client, "What causes a stall?", [("abc123", "text")], config)

    assert client.with_options_kwargs == {"max_retries": 7, "timeout": 12.0}
    parse_kwargs = client.scoped.messages.parse_kwargs
    assert parse_kwargs["model"] == "claude-sonnet-5"
    assert parse_kwargs["max_tokens"] == 999
    assert parse_kwargs["thinking"] == {"type": "disabled"}
    assert parse_kwargs["output_format"] is GeneratedAnswer
    assert result is canned


@pytest.mark.slow
@pytest.mark.live_api
def test_generate_answer_cites_real_chunk_for_in_scope_question():
    # Probe-verified 2026-07-13 against claude-sonnet-5: cited exactly ["stall001"],
    # answer_text "A stall occurs when the wing exceeds its critical angle of attack,
    # which causes a sudden loss of lift [stall001]." unrelated1 correctly excluded.
    client = anthropic.Anthropic(api_key=Settings().anthropic_api_key)
    config = GenerationConfig()
    chunks = [
        (
            "stall001",
            "A stall occurs when the wing exceeds its critical angle of attack, "
            "causing a sudden loss of lift.",
        ),
        ("unrelated1", "The FAA Wings Program offers recurrent training credit."),
    ]

    result = generate_answer(client, "What causes a stall?", chunks, config)

    assert "stall001" in result.citations
    assert "unrelated1" not in result.citations


@pytest.mark.slow
@pytest.mark.live_api
def test_generate_answer_admits_insufficient_context_for_off_topic_chunks():
    # Probe-verified 2026-07-13 against claude-sonnet-5. First pass failed: the model
    # cited [wb01] even while explaining it doesn't answer the question ("the only
    # excerpt available discusses..."). Fixed by making the prompt explicit that
    # `citations` must be empty when nothing supports the answer, even if the answer
    # text mentions what an excerpt covers instead. Re-verified: citations == [].
    client = anthropic.Anthropic(api_key=Settings().anthropic_api_key)
    config = GenerationConfig()
    chunks = [("wb01", "Weight and balance must be computed before every flight.")]

    result = generate_answer(
        client, "Does this handbook cover helicopter autorotation?", chunks, config
    )

    assert result.citations == []
