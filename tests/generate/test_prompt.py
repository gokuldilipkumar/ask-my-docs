from generate.prompt import PROMPT_VERSION, build_prompt


def test_build_prompt_embeds_question_and_chunk_ids():
    chunks = [("abc123", "Stalls occur when the critical angle of attack is exceeded.")]

    prompt = build_prompt("What causes a stall?", chunks)

    assert "What causes a stall?" in prompt
    assert "abc123" in prompt
    assert "Stalls occur when" in prompt


def test_build_prompt_instructs_context_only_and_citation_by_id():
    prompt = build_prompt("any question", [("id1", "some text")])

    assert "citations" in prompt.lower()
    assert "only" in prompt.lower()  # "answer only from the provided context"


def test_prompt_version_is_answer_v2():
    assert PROMPT_VERSION == "answer_v2"


def test_build_prompt_does_not_instruct_inline_bracket_citation():
    prompt = build_prompt("any question", [("id1", "some text")])

    assert "square brackets" not in prompt.lower()


def test_build_prompt_still_instructs_the_citations_field_contract():
    prompt = build_prompt("any question", [("id1", "some text")])

    assert "citations" in prompt.lower()
    assert "only" in prompt.lower()  # "supports a claim... only if"
