from pathlib import Path

from pydantic import BaseModel, ValidationError

from config.settings import EvalConfig

_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / "judge_v1.md"


class AnswerJudgment(BaseModel):
    correct: bool
    complete: bool
    reasoning: str


def judge_answer(
    client, question: str, answer_text: str, reference_notes: str, config: EvalConfig
) -> AnswerJudgment:
    prompt = _TEMPLATE_PATH.read_text().format(
        question=question, answer_text=answer_text, reference_notes=reference_notes
    )

    scoped_client = client.with_options(max_retries=config.judge_max_retries, timeout=config.judge_timeout_seconds)
    try:
        response = scoped_client.messages.parse(
            model=config.judge_model,
            max_tokens=config.judge_max_tokens,
            temperature=config.judge_temperature,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
            output_format=AnswerJudgment,
        )
    except ValidationError as e:
        raise RuntimeError(
            f"Answer-quality judge response could not be parsed, likely truncated by "
            f"eval.judge_max_tokens (currently {config.judge_max_tokens})."
        ) from e

    return response.parsed_output
