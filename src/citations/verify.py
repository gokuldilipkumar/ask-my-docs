from pydantic import ValidationError

from citations.prompt import build_verify_prompt
from citations.schema import VerificationResult, VerifiedAnswer
from config.settings import CitationConfig
from generate.schema import GeneratedAnswer
from observability.context import ObservabilityContext, noop_observability
from observability.usage import report_usage


def verify_citations(
    client,
    question: str,
    answer: GeneratedAnswer,
    chunk_texts: dict[str, str],
    config: CitationConfig,
    observability: ObservabilityContext | None = None,
) -> VerifiedAnswer:
    if not answer.citations:
        return VerifiedAnswer(
            answer_text=answer.answer_text, citations=[], coverage=1.0, low_confidence=False
        )

    track_cost = observability is not None
    observability = observability or noop_observability()
    scoped_client = client.with_options(max_retries=config.max_retries, timeout=config.timeout_seconds)
    excerpts = [(cid, chunk_texts[cid]) for cid in answer.citations]
    prompt = build_verify_prompt(question, answer.answer_text, excerpts)
    with observability.tracer.span("citations.verify", as_type="generation", model=config.judge_model) as span:
        try:
            response = scoped_client.messages.parse(
                model=config.judge_model,
                max_tokens=config.max_tokens,
                temperature=config.judge_temperature,
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": prompt}],
                output_format=VerificationResult,
            )
        except ValidationError as e:
            raise RuntimeError(
                f"Anthropic judge response could not be parsed as VerificationResult, likely "
                f"because it was truncated by max_tokens (currently {config.max_tokens}). "
                f"Consider raising citations.max_tokens."
            ) from e
        if track_cost:
            cost = report_usage(
                config.judge_model, response.usage.input_tokens, response.usage.output_tokens, observability.config
            )
            span.update(
                usage_details={"input": response.usage.input_tokens, "output": response.usage.output_tokens},
                cost_details={"total": cost},
            )

    verdicts = {v.chunk_id: v.supported for v in response.parsed_output.verdicts}
    supported = [cid for cid in answer.citations if verdicts.get(cid, False)]
    coverage = len(supported) / len(answer.citations)
    return VerifiedAnswer(
        answer_text=answer.answer_text,
        citations=supported,
        coverage=coverage,
        low_confidence=coverage < config.low_confidence_threshold,
    )
