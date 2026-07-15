from types import SimpleNamespace

import anthropic
import pytest

from config.settings import GenerationConfig, ObservabilityConfig, Settings
from generate.client import generate_answer
from generate.schema import GeneratedAnswer
from observability.context import ObservabilityContext


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
                usage = SimpleNamespace(input_tokens=10, output_tokens=5)

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


def test_generate_answer_opens_a_generation_span_and_reports_usage():
    canned = GeneratedAnswer(answer_text="Stalls happen when...", citations=["abc123"])

    class FakeMessages:
        def parse(self, **kwargs):
            class FakeResponse:
                parsed_output = canned
                usage = SimpleNamespace(input_tokens=10, output_tokens=5)

            return FakeResponse()

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    class SpyTracer:
        def __init__(self):
            self.spans = []

        def span(self, name, *, as_type="span", model=None):
            self.spans.append({"name": name, "as_type": as_type, "model": model})
            return _SpySpanCtx(self)

    class _SpySpanCtx:
        def __init__(self, tracer):
            self.tracer = tracer
            self.update_calls = []

        def __enter__(self):
            return self

        def update(self, **kwargs):
            self.update_calls.append(kwargs)

        def __exit__(self, *exc):
            return False

    config = GenerationConfig(model="claude-sonnet-5")
    tracer = SpyTracer()
    observability = ObservabilityContext(tracer=tracer, config=ObservabilityConfig(price_table={}))

    generate_answer(FakeClient(), "q", [("abc123", "text")], config, observability=observability)

    assert tracer.spans == [{"name": "generate.answer", "as_type": "generation", "model": "claude-sonnet-5"}]


def test_generate_answer_defaults_to_noop_tracer_when_observability_omitted():
    canned = GeneratedAnswer(answer_text="Stalls happen when...", citations=["abc123"])

    class FakeMessages:
        def parse(self, **kwargs):
            class FakeResponse:
                parsed_output = canned
                usage = SimpleNamespace(input_tokens=10, output_tokens=5)

            return FakeResponse()

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    config = GenerationConfig()

    # No observability argument at all -- unchanged existing call shape must keep working.
    result = generate_answer(FakeClient(), "q", [("abc123", "text")], config)

    assert result is canned


def test_generate_answer_raises_clear_error_on_truncated_output():
    # Reproduces a real 2026-07-13 spot-check crash: a detailed question exceeded
    # max_tokens=1024, truncating the model's JSON mid-string. client.messages.parse
    # raised a raw pydantic.ValidationError three SDK frames deep ("EOF while parsing
    # a string") instead of anything actionable. generate_answer must catch that and
    # raise a message pointing at the actual cause (max_tokens), not let a bare
    # pydantic internal error surface to the caller.
    class FakeMessages:
        def parse(self, **kwargs):
            GeneratedAnswer.model_validate_json('{"answer_text": "During u')  # raises

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    config = GenerationConfig(max_tokens=1024)

    with pytest.raises(RuntimeError, match="max_tokens"):
        generate_answer(FakeClient(), "any question", [("a", "text")], config)


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
