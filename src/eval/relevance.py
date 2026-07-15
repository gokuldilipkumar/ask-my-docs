from pathlib import Path

from pydantic import BaseModel

from config.settings import EvalConfig
from eval.llm_call import call_structured_judge

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
    result = call_structured_judge(client, prompt, RelevanceLabelingResult, config, "Relevance judge")

    verdicts = {v.chunk_id: v.relevant for v in result.verdicts}
    return [chunk_id for chunk_id, _ in candidates if verdicts.get(chunk_id, False)]
