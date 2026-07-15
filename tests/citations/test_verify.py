from types import SimpleNamespace

import anthropic
import pytest

from citations.schema import CitationVerdict, VerificationResult, VerifiedAnswer
from citations.verify import verify_citations
from config.settings import CitationConfig, ObservabilityConfig, Settings
from generate.schema import GeneratedAnswer
from observability.context import ObservabilityContext


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


def test_verify_citations_configures_client_and_strips_unsupported():
    verdicts = VerificationResult(
        verdicts=[
            CitationVerdict(chunk_id="abc123", supported=True),
            CitationVerdict(chunk_id="off999", supported=False),
        ]
    )

    class FakeMessages:
        def __init__(self):
            self.parse_kwargs = None

        def parse(self, **kwargs):
            self.parse_kwargs = kwargs

            class FakeResponse:
                parsed_output = verdicts
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
    config = CitationConfig(
        judge_model="claude-haiku-4-5-20251001",
        judge_temperature=0.0,
        max_tokens=777,
        max_retries=5,
        timeout_seconds=9.0,
    )
    answer = GeneratedAnswer(
        answer_text="A stall occurs when critical AoA is exceeded [abc123].",
        citations=["abc123", "off999"],
    )
    chunk_texts = {"abc123": "Stalls occur at critical AoA.", "off999": "The Wings program..."}

    result = verify_citations(client, "What causes a stall?", answer, chunk_texts, config)

    assert client.with_options_kwargs == {"max_retries": 5, "timeout": 9.0}
    parse_kwargs = client.scoped.messages.parse_kwargs
    assert parse_kwargs["model"] == "claude-haiku-4-5-20251001"
    assert parse_kwargs["max_tokens"] == 777
    assert parse_kwargs["temperature"] == 0.0
    assert parse_kwargs["thinking"] == {"type": "disabled"}
    assert parse_kwargs["output_format"] is VerificationResult
    assert result.citations == ["abc123"]
    assert result.coverage == 0.5
    assert result.low_confidence is True  # 0.5 < default threshold 0.7


def test_verify_citations_treats_missing_verdict_as_unsupported():
    # Judge only returned a verdict for one of two cited chunks - the missing one
    # must default to unsupported (fail-safe), not silently kept.
    verdicts = VerificationResult(verdicts=[CitationVerdict(chunk_id="abc123", supported=True)])

    class FakeMessages:
        def parse(self, **kwargs):
            class FakeResponse:
                parsed_output = verdicts
                usage = SimpleNamespace(input_tokens=10, output_tokens=5)

            return FakeResponse()

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    answer = GeneratedAnswer(answer_text="...", citations=["abc123", "missing999"])
    chunk_texts = {"abc123": "text a", "missing999": "text b"}

    result = verify_citations(FakeClient(), "q", answer, chunk_texts, CitationConfig())

    assert result.citations == ["abc123"]
    assert result.coverage == 0.5


def test_verify_citations_opens_a_generation_span_and_reports_usage():
    verdicts = VerificationResult(verdicts=[CitationVerdict(chunk_id="abc123", supported=True)])

    class FakeMessages:
        def parse(self, **kwargs):
            class FakeResponse:
                parsed_output = verdicts
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
            return _SpySpanCtx()

    class _SpySpanCtx:
        def __enter__(self):
            return self

        def update(self, **kwargs):
            pass

        def __exit__(self, *exc):
            return False

    answer = GeneratedAnswer(answer_text="...[abc123]", citations=["abc123"])
    config = CitationConfig(judge_model="claude-haiku-4-5-20251001")
    tracer = SpyTracer()
    observability = ObservabilityContext(tracer=tracer, config=ObservabilityConfig(price_table={}))

    verify_citations(FakeClient(), "q", answer, {"abc123": "text"}, config, observability=observability)

    assert tracer.spans == [
        {"name": "citations.verify", "as_type": "generation", "model": "claude-haiku-4-5-20251001"}
    ]


def test_verify_citations_raises_clear_error_on_truncated_output():
    class FakeMessages:
        def parse(self, **kwargs):
            VerificationResult.model_validate_json('{"verdicts": [{"chunk_id": "a')  # raises

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    answer = GeneratedAnswer(answer_text="...", citations=["a"])
    config = CitationConfig(max_tokens=50)

    with pytest.raises(RuntimeError, match="max_tokens"):
        verify_citations(FakeClient(), "q", answer, {"a": "text"}, config)


@pytest.mark.slow
@pytest.mark.live_api
def test_verify_citations_keeps_supported_and_strips_unsupported_on_real_judge():
    # Probe-verified 2026-07-14 against claude-haiku-4-5-20251001: verdicts=[
    # CitationVerdict(chunk_id='stall001', supported=True),
    # CitationVerdict(chunk_id='unrelated1', supported=False)] - exactly the
    # discrimination this test asserts.
    client = anthropic.Anthropic(api_key=Settings().anthropic_api_key)
    config = CitationConfig()
    answer = GeneratedAnswer(
        answer_text="A stall occurs when the wing exceeds its critical angle of attack [stall001].",
        citations=["stall001", "unrelated1"],
    )
    chunk_texts = {
        "stall001": "A stall occurs when the wing exceeds its critical angle of attack, "
        "causing a sudden loss of lift.",
        "unrelated1": "The FAA Wings Program offers recurrent training credit.",
    }

    result = verify_citations(client, "What causes a stall?", answer, chunk_texts, config)

    assert "stall001" in result.citations
    assert "unrelated1" not in result.citations
    assert result.coverage < 1.0
