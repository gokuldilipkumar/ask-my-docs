from pydantic import ValidationError

from config.settings import GenerationConfig
from generate.prompt import build_prompt
from generate.schema import GeneratedAnswer

_NO_CONTEXT_ANSWER = "I don't have information about that in this handbook."


def generate_answer(
    client, question: str, chunks: list[tuple[str, str]], config: GenerationConfig
) -> GeneratedAnswer:
    if not chunks:
        return GeneratedAnswer(answer_text=_NO_CONTEXT_ANSWER, citations=[])

    scoped_client = client.with_options(max_retries=config.max_retries, timeout=config.timeout_seconds)
    prompt = build_prompt(question, chunks)
    try:
        response = scoped_client.messages.parse(
            model=config.model,
            max_tokens=config.max_tokens,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
            output_format=GeneratedAnswer,
        )
    except ValidationError as e:
        raise RuntimeError(
            f"Anthropic response could not be parsed as GeneratedAnswer, likely because "
            f"it was truncated by max_tokens (currently {config.max_tokens}). "
            f"Consider raising generation.max_tokens."
        ) from e
    return response.parsed_output
