import pytest
from pydantic import ValidationError

from config.settings import EvalConfig
from eval.relevance import RelevanceLabelingResult, RelevanceVerdict, label_relevance


def test_label_relevance_returns_only_relevant_chunk_ids():
    verdicts = RelevanceLabelingResult(
        verdicts=[
            RelevanceVerdict(chunk_id="stall001", relevant=True),
            RelevanceVerdict(chunk_id="wings01", relevant=False),
        ]
    )

    class FakeMessages:
        def __init__(self):
            self.parse_kwargs = None

        def parse(self, **kwargs):
            self.parse_kwargs = kwargs

            class FakeResponse:
                parsed_output = verdicts

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
    config = EvalConfig(judge_max_tokens=777, judge_max_retries=5, judge_timeout_seconds=9.0)
    candidates = [("stall001", "text a"), ("wings01", "text b")]

    result = label_relevance(client, "What causes a stall?", candidates, config)

    assert client.with_options_kwargs == {"max_retries": 5, "timeout": 9.0}
    parse_kwargs = client.scoped.messages.parse_kwargs
    assert parse_kwargs["model"] == config.judge_model
    assert parse_kwargs["max_tokens"] == 777
    assert parse_kwargs["thinking"] == {"type": "disabled"}
    assert parse_kwargs["output_format"] is RelevanceLabelingResult
    assert result == ["stall001"]


def test_label_relevance_treats_missing_verdict_as_not_relevant():
    verdicts = RelevanceLabelingResult(verdicts=[RelevanceVerdict(chunk_id="a", relevant=True)])

    class FakeMessages:
        def parse(self, **kwargs):
            class FakeResponse:
                parsed_output = verdicts

            return FakeResponse()

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    candidates = [("a", "text a"), ("missing999", "text b")]

    result = label_relevance(FakeClient(), "q", candidates, EvalConfig())

    assert result == ["a"]


def test_label_relevance_raises_clear_error_on_truncated_output():
    class FakeMessages:
        def parse(self, **kwargs):
            RelevanceLabelingResult.model_validate_json('{"verdicts": [{"chunk_id": "a')  # raises

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    config = EvalConfig(judge_max_tokens=10)

    with pytest.raises(RuntimeError, match="judge_max_tokens"):
        label_relevance(FakeClient(), "q", [("a", "text")], config)
