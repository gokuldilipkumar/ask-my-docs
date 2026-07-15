from pydantic import ValidationError

from config.settings import GenerationConfig
from generate.prompt import NO_CONTEXT_ANSWER, build_prompt
from generate.schema import GeneratedAnswer
from observability.context import ObservabilityContext, noop_observability
from observability.usage import report_usage


def generate_answer(
    client, question: str, chunks: list[tuple[str, str]], config: GenerationConfig,
    observability: ObservabilityContext | None = None,
) -> GeneratedAnswer:
    if not chunks:
        return GeneratedAnswer(answer_text=NO_CONTEXT_ANSWER, citations=[])

    track_cost = observability is not None
    observability = observability or noop_observability()
    scoped_client = client.with_options(max_retries=config.max_retries, timeout=config.timeout_seconds)
    prompt = build_prompt(question, chunks)
    with observability.tracer.span("generate.answer", as_type="generation", model=config.model) as span:
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
        if track_cost:
            cost = report_usage(
                config.model, response.usage.input_tokens, response.usage.output_tokens, observability.config
            )
            span.update(
                usage_details={"input": response.usage.input_tokens, "output": response.usage.output_tokens},
                cost_details={"total": cost},
            )
    return response.parsed_output
