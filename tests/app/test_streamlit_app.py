from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from ingest.chunk_metadata import ChunkMetadata

APP_PATH = str(Path(__file__).resolve().parents[2] / "src" / "app" / "streamlit_app.py")


class FakeVerified:
    answer_text = "Stalls occur when the critical angle of attack is exceeded."
    citations = []
    coverage = 1.0
    low_confidence = False


class FakeVerifiedWithCitations:
    answer_text = "Partial info found."
    citations = ["abc123"]
    coverage = 0.4
    low_confidence = True


def test_submitting_a_question_shows_the_answer(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(APP_PATH)

    with patch("citations.pipeline.answer_with_verified_citations", return_value=FakeVerified()), \
         patch("observability.daily_cost.format_daily_cost", return_value="$0.0000"):
        at.run()
        at.chat_input[0].set_value("What causes a stall?").run()

    assert "Stalls occur when" in at.chat_message[-1].markdown[0].value


def test_answer_shows_resolved_sources_and_low_confidence_warning(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(APP_PATH)

    meta = {
        "abc123": ChunkMetadata(chapter_number=4, chapter_title="Energy Management", section_title="Total Energy")
    }

    with patch("citations.pipeline.answer_with_verified_citations", return_value=FakeVerifiedWithCitations()), \
         patch("observability.daily_cost.format_daily_cost", return_value="$0.0000"), \
         patch("ingest.chunk_metadata.load_chunk_metadata", return_value=meta):
        at.run()
        at.chat_input[0].set_value("What causes a stall?").run()

    all_markdown = " ".join(m.value for m in at.markdown)
    assert "Ch. 4: Energy Management" in all_markdown
    assert "Total Energy" in all_markdown
    assert "abc123" not in all_markdown
    assert len(at.warning) == 1


def test_missing_citation_metadata_falls_back_to_raw_chunk_id(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(APP_PATH)

    with patch("citations.pipeline.answer_with_verified_citations", return_value=FakeVerifiedWithCitations()), \
         patch("observability.daily_cost.format_daily_cost", return_value="$0.0000"), \
         patch("ingest.chunk_metadata.load_chunk_metadata", return_value={}):
        at.run()
        at.chat_input[0].set_value("What causes a stall?").run()

    all_markdown = " ".join(m.value for m in at.markdown)
    assert "abc123 (citation detail unavailable)" in all_markdown


def test_sidebar_shows_daily_cost_and_no_warning_under_cap(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(APP_PATH)

    with patch("citations.pipeline.answer_with_verified_citations", return_value=FakeVerified()), \
         patch("observability.daily_cost.format_daily_cost", return_value="$0.0421"), \
         patch("observability.daily_cost.check_budget", return_value=False):
        at.run()

    assert at.sidebar.metric[0].value == "$0.0421"
    assert len(at.sidebar.warning) == 0


def test_sidebar_shows_budget_cap_warning_when_exceeded(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(APP_PATH)

    with patch("citations.pipeline.answer_with_verified_citations", return_value=FakeVerified()), \
         patch("observability.daily_cost.format_daily_cost", return_value="$6.0000"), \
         patch("observability.daily_cost.check_budget", return_value=True):
        at.run()

    assert len(at.sidebar.warning) == 1


def test_pipeline_error_shows_st_error_and_session_stays_usable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(APP_PATH)

    with patch("citations.pipeline.answer_with_verified_citations", side_effect=RuntimeError("boom")), \
         patch("observability.daily_cost.format_daily_cost", return_value="$0.0000"), \
         patch("observability.daily_cost.check_budget", return_value=False):
        at.run()
        at.chat_input[0].set_value("What causes a stall?").run()

    assert len(at.error) == 1
    assert "boom" in at.error[0].value
    assert not any(turn["role"] == "assistant" for turn in at.session_state["history"])

    with patch("citations.pipeline.answer_with_verified_citations", return_value=FakeVerified()), \
         patch("observability.daily_cost.format_daily_cost", return_value="$0.0000"), \
         patch("observability.daily_cost.check_budget", return_value=False):
        at.chat_input[0].set_value("A follow-up question?").run()

    assert any(turn["role"] == "assistant" for turn in at.session_state["history"])
