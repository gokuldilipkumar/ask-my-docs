import pytest
from pydantic import ValidationError

from config.settings import EvalConfig
from eval.judge import AnswerJudgment, judge_answer


def test_judge_answer_configures_client_and_returns_judgment():
    judgment = AnswerJudgment(correct=True, complete=False, reasoning="Covers short-field only.")

    class FakeMessages:
        def __init__(self):
            self.parse_kwargs = None

        def parse(self, **kwargs):
            self.parse_kwargs = kwargs

            class FakeResponse:
                parsed_output = judgment

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

    result = judge_answer(client, "q", "answer text", "must cover X and Y", config)

    assert client.with_options_kwargs == {"max_retries": 5, "timeout": 9.0}
    parse_kwargs = client.scoped.messages.parse_kwargs
    assert parse_kwargs["model"] == config.judge_model
    assert parse_kwargs["max_tokens"] == 777
    assert parse_kwargs["thinking"] == {"type": "disabled"}
    assert parse_kwargs["output_format"] is AnswerJudgment
    assert result.correct is True
    assert result.complete is False


def test_judge_answer_raises_clear_error_on_truncated_output():
    class FakeMessages:
        def parse(self, **kwargs):
            AnswerJudgment.model_validate_json('{"correct": tr')  # raises

    class FakeScopedClient:
        messages = FakeMessages()

    class FakeClient:
        def with_options(self, **kwargs):
            return FakeScopedClient()

    with pytest.raises(RuntimeError, match="judge_max_tokens"):
        judge_answer(FakeClient(), "q", "a", "notes", EvalConfig(judge_max_tokens=10))
