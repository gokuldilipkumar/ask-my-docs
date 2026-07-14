from pathlib import Path

PROMPT_VERSION = "verify_v1"
_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / f"{PROMPT_VERSION}.md"


def build_verify_prompt(question: str, answer_text: str, citations: list[tuple[str, str]]) -> str:
    template = _TEMPLATE_PATH.read_text()
    context = "\n\n".join(f"[{chunk_id}] {text}" for chunk_id, text in citations)
    return template.format(question=question, answer_text=answer_text, context=context)
