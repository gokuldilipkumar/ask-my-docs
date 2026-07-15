import pytest

from config.settings import EvalConfig
from eval.relevance import RelevanceLabelingResult, RelevanceVerdict, label_relevance


def test_label_relevance_returns_only_relevant_chunk_ids(make_fake_structured_client):
    verdicts = RelevanceLabelingResult(
        verdicts=[
            RelevanceVerdict(chunk_id="stall001", relevant=True),
            RelevanceVerdict(chunk_id="wings01", relevant=False),
        ]
    )
    client = make_fake_structured_client(parsed_output=verdicts)
    config = EvalConfig(judge_max_tokens=777, judge_max_retries=5, judge_timeout_seconds=9.0)
    candidates = [("stall001", "text a"), ("wings01", "text b")]

    result = label_relevance(client, "What causes a stall?", candidates, config)

    assert client.with_options_kwargs == {"max_retries": 5, "timeout": 9.0}
    assert client.parse_kwargs["model"] == config.judge_model
    assert client.parse_kwargs["max_tokens"] == 777
    assert client.parse_kwargs["thinking"] == {"type": "disabled"}
    assert client.parse_kwargs["output_format"] is RelevanceLabelingResult
    assert result == ["stall001"]


def test_label_relevance_treats_missing_verdict_as_not_relevant(make_fake_structured_client):
    verdicts = RelevanceLabelingResult(verdicts=[RelevanceVerdict(chunk_id="a", relevant=True)])
    client = make_fake_structured_client(parsed_output=verdicts)
    candidates = [("a", "text a"), ("missing999", "text b")]

    result = label_relevance(client, "q", candidates, EvalConfig())

    assert result == ["a"]


def test_label_relevance_raises_clear_error_on_truncated_output(make_fake_structured_client):
    client = make_fake_structured_client(truncate=True)
    config = EvalConfig(judge_max_tokens=10)

    with pytest.raises(RuntimeError, match="judge_max_tokens"):
        label_relevance(client, "q", [("a", "text")], config)
