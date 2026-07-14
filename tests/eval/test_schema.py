from pathlib import Path

from eval.schema import GoldenQuestion, load_golden_questions


def test_load_golden_questions_parses_seeded_yaml(tmp_path):
    path = tmp_path / "questions.yaml"
    path.write_text(
        "- id: q1_vmc_vso\n"
        "  question: \"What's the difference between VMC and VSO?\"\n"
        "  relevant_chunk_ids: []\n"
        "  reference_notes: \"\"\n"
        "  auto_generated: false\n"
        "  reviewed: false\n"
    )

    questions = load_golden_questions(path)

    assert len(questions) == 1
    assert isinstance(questions[0], GoldenQuestion)
    assert questions[0].id == "q1_vmc_vso"


def test_real_golden_file_has_the_eight_confirmed_sample_questions():
    questions = load_golden_questions(Path("eval/golden/questions.yaml"))

    assert len(questions) == 8
    assert {q.id for q in questions} == {
        "q1_vmc_vso",
        "q2_secondary_stall",
        "q3_shortfield_softfield",
        "q4_crosswind_errors",
        "q5_energy_rules",
        "q6_upset_recovery",
        "q7_wings_program",
        "q8_autorotation_oos",
    }
    assert all(q.reviewed is True for q in questions)  # reviewed by Chunk 6.3's manual pass
    assert all(q.reference_notes for q in questions)
