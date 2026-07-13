from pathlib import Path

PROMPT_VERSION = "answer_v1"
_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / f"{PROMPT_VERSION}.md"


def build_prompt(question: str, chunks: list[tuple[str, str]]) -> str:
    template = _TEMPLATE_PATH.read_text()
    context = "\n\n".join(f"[{chunk_id}] {text}" for chunk_id, text in chunks)
    return template.format(question=question, context=context)
