from pathlib import Path

from pydantic import BaseModel, ValidationError

from config.settings import EvalConfig

_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / "relevance_v1.md"


class RelevanceVerdict(BaseModel):
    chunk_id: str
    relevant: bool


class RelevanceLabelingResult(BaseModel):
    verdicts: list[RelevanceVerdict]


def label_relevance(
    client, question: str, candidates: list[tuple[str, str]], config: EvalConfig
) -> list[str]:
    context = "\n\n".join(f"[{chunk_id}] {text}" for chunk_id, text in candidates)
    prompt = _TEMPLATE_PATH.read_text().format(question=question, context=context)

    scoped_client = client.with_options(max_retries=config.judge_max_retries, timeout=config.judge_timeout_seconds)
    try:
        response = scoped_client.messages.parse(
            model=config.judge_model,
            max_tokens=config.judge_max_tokens,
            temperature=config.judge_temperature,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
            output_format=RelevanceLabelingResult,
        )
    except ValidationError as e:
        raise RuntimeError(
            f"Relevance judge response could not be parsed, likely truncated by "
            f"eval.judge_max_tokens (currently {config.judge_max_tokens})."
        ) from e

    verdicts = {v.chunk_id: v.relevant for v in response.parsed_output.verdicts}
    return [chunk_id for chunk_id, _ in candidates if verdicts.get(chunk_id, False)]
