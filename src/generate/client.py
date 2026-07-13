from config.settings import GenerationConfig
from generate.prompt import build_prompt
from generate.schema import GeneratedAnswer

_NO_CONTEXT_ANSWER = "I don't have information about that in this handbook."


def generate_answer(
    client, question: str, chunks: list[tuple[str, str]], config: GenerationConfig
) -> GeneratedAnswer:
    if not chunks:
        return GeneratedAnswer(answer_text=_NO_CONTEXT_ANSWER, citations=[])
    raise NotImplementedError  # real API call lands in Chunk 4.3
