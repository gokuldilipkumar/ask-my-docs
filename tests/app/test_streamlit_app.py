from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parents[2] / "src" / "app" / "streamlit_app.py")


class FakeVerified:
    answer_text = "Stalls occur when the critical angle of attack is exceeded."
    citations = []
    coverage = 1.0
    low_confidence = False


def test_submitting_a_question_shows_the_answer(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(APP_PATH)

    with patch("citations.pipeline.answer_with_verified_citations", return_value=FakeVerified()), \
         patch("observability.daily_cost.get_daily_total", return_value=0.0):
        at.run()
        at.chat_input[0].set_value("What causes a stall?").run()

    assert "Stalls occur when" in at.chat_message[-1].markdown[0].value
