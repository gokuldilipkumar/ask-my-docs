import anthropic
import pytest

from config.settings import EvalConfig, Settings
from eval.judge import AnswerJudgment, judge_answer


def test_judge_answer_configures_client_and_returns_judgment(make_fake_structured_client):
    judgment = AnswerJudgment(correct=True, complete=False, reasoning="Covers short-field only.")
    client = make_fake_structured_client(parsed_output=judgment)
    config = EvalConfig(judge_max_tokens=777, judge_max_retries=5, judge_timeout_seconds=9.0)

    result = judge_answer(client, "q", "answer text", "must cover X and Y", config)

    assert client.with_options_kwargs == {"max_retries": 5, "timeout": 9.0}
    assert client.parse_kwargs["model"] == config.judge_model
    assert client.parse_kwargs["max_tokens"] == 777
    assert client.parse_kwargs["thinking"] == {"type": "disabled"}
    assert client.parse_kwargs["output_format"] is AnswerJudgment
    assert result.correct is True
    assert result.complete is False


def test_judge_answer_raises_clear_error_on_truncated_output(make_fake_structured_client):
    client = make_fake_structured_client(truncate=True)

    with pytest.raises(RuntimeError, match="judge_max_tokens"):
        judge_answer(client, "q", "a", "notes", EvalConfig(judge_max_tokens=10))


@pytest.mark.slow
@pytest.mark.live_api
def test_judge_answer_distinguishes_correct_complete_from_incomplete_on_real_judge():
    client = anthropic.Anthropic(api_key=Settings().anthropic_api_key)
    config = EvalConfig()
    reference_notes = (
        "Short-field takeoff: apply maximum available power before brake release, hold/rotate "
        "at best angle-of-climb speed (Vx) to clear an obstacle. Soft-field takeoff: minimize "
        "weight on the wheels via back-elevator pressure to avoid bogging down in soft/loose "
        "surfaces, use ground effect to accelerate before climbing."
    )

    # Probe run (2026-07-14, real API, claude-haiku-4-5-20251001):
    # complete   -> correct=True,  complete=True  (reasoning: "all essential elements from
    #               the reference notes are present... concise but complete")
    # half_answer -> correct=True, complete=False (reasoning: "incomplete because it fails
    #               to address the soft-field takeoff procedure at all... only addresses
    #               half of the comparison question")
    # Judge discriminates correctness from completeness as designed: the half-answer is
    # judged factually correct (nothing it says is wrong) but incomplete (it omits half
    # the comparison) -- exactly the failure mode `correct` alone would have missed.
    complete = judge_answer(
        client,
        "How does a short-field takeoff differ from a soft-field takeoff?",
        "Short-field takeoffs use maximum power before brake release and climb at best "
        "angle-of-climb speed to clear an obstacle. Soft-field takeoffs use minimum weight "
        "on the wheels via back pressure and accelerate in ground effect before climbing.",
        reference_notes,
        config,
    )
    half_answer = judge_answer(
        client,
        "How does a short-field takeoff differ from a soft-field takeoff?",
        "Short-field takeoffs use maximum power before brake release and climb at best "
        "angle-of-climb speed to clear an obstacle.",
        reference_notes,
        config,
    )

    assert complete.correct is True and complete.complete is True
    assert half_answer.complete is False
