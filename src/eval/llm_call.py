from pydantic import BaseModel, ValidationError

from config.settings import EvalConfig, ObservabilityConfig
from observability.usage import report_usage


def call_structured_judge(
    client, prompt: str, output_format: type[BaseModel], config: EvalConfig, error_label: str,
    # Config only, not a full ObservabilityContext: eval judges are deliberately cost-tracked
    # but never traced (no tracer.span here) -- they run in the offline eval flow, not the
    # traced query-time path the design doc diagrams (bm25/vector/fusion/rerank/generate/verify).
    observability_config: ObservabilityConfig | None = None,
) -> BaseModel:
    scoped_client = client.with_options(max_retries=config.judge_max_retries, timeout=config.judge_timeout_seconds)
    try:
        response = scoped_client.messages.parse(
            model=config.judge_model,
            max_tokens=config.judge_max_tokens,
            temperature=config.judge_temperature,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
            output_format=output_format,
        )
    except ValidationError as e:
        raise RuntimeError(
            f"{error_label} response could not be parsed, likely truncated by "
            f"eval.judge_max_tokens (currently {config.judge_max_tokens})."
        ) from e
    if observability_config is not None:
        report_usage(config.judge_model, response.usage.input_tokens, response.usage.output_tokens, observability_config)
    return response.parsed_output
