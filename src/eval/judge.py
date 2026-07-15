from pathlib import Path

from pydantic import BaseModel

from config.settings import EvalConfig, ObservabilityConfig
from eval.llm_call import call_structured_judge

_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / "judge_v1.md"


class AnswerJudgment(BaseModel):
    correct: bool
    complete: bool
    reasoning: str


def judge_answer(
    client, question: str, answer_text: str, reference_notes: str, config: EvalConfig,
    observability_config: ObservabilityConfig | None = None,
) -> AnswerJudgment:
    prompt = _TEMPLATE_PATH.read_text().format(
        question=question, answer_text=answer_text, reference_notes=reference_notes
    )
    return call_structured_judge(
        client, prompt, AnswerJudgment, config, "Answer-quality judge", observability_config=observability_config
    )
