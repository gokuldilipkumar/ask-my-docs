from citations.prompt import PROMPT_VERSION, build_verify_prompt


def test_build_verify_prompt_embeds_question_answer_and_chunk_ids():
    citations = [("abc123", "Stalls occur when the critical angle of attack is exceeded.")]

    prompt = build_verify_prompt(
        "What causes a stall?",
        "A stall occurs when the critical angle of attack is exceeded [abc123].",
        citations,
    )

    assert "What causes a stall?" in prompt
    assert "abc123" in prompt
    assert "critical angle of attack is exceeded" in prompt


def test_build_verify_prompt_instructs_per_citation_support_judgment():
    prompt = build_verify_prompt("any question", "any answer", [("id1", "some text")])

    assert "support" in prompt.lower()


def test_prompt_version_is_exposed():
    assert PROMPT_VERSION == "verify_v1"
