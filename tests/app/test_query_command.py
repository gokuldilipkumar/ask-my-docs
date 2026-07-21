import pytest
from typer.testing import CliRunner

from app.main import app
from ingest.bm25_index import build_bm25_index
from ingest.vector_index import build_vector_index

runner = CliRunner()


def test_query_command_prints_answer_citations_and_cost(monkeypatch, tmp_path):
    from app import main as app_main

    class FakeVerified:
        answer_text = "Stalls occur when the critical angle of attack is exceeded."
        citations = ["abc123"]
        coverage = 1.0
        low_confidence = False

    def fake_answer_with_verified_citations(question, client, bm25_dir, vector_db_path, settings):
        assert question == "What causes a stall?"
        return FakeVerified()

    monkeypatch.setattr(app_main, "answer_with_verified_citations", fake_answer_with_verified_citations)
    monkeypatch.setattr(app_main, "format_daily_cost", lambda db_path: "$0.0421")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = runner.invoke(app, ["query", "--question", "What causes a stall?"])

    assert result.exit_code == 0
    assert "Stalls occur when" in result.stdout
    assert "abc123" in result.stdout
    assert "0.0421" in result.stdout


def test_query_command_flags_low_confidence(monkeypatch):
    from app import main as app_main

    class FakeVerified:
        answer_text = "Partial answer."
        citations = ["abc123"]
        coverage = 0.3
        low_confidence = True

    monkeypatch.setattr(
        app_main, "answer_with_verified_citations", lambda *a, **k: FakeVerified()
    )
    monkeypatch.setattr(app_main, "format_daily_cost", lambda db_path: "$0.0000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = runner.invoke(app, ["query", "--question", "q"])

    assert result.exit_code == 0
    assert "low confidence" in result.stdout.lower()


@pytest.mark.slow
@pytest.mark.live_api
def test_query_command_answers_for_real(tmp_path, make_chunk, monkeypatch):
    # Deliberately does not chdir -- config.yaml/.env must still resolve from the
    # repo root for a real ANTHROPIC_API_KEY; --index alone points at the tiny
    # synthetic corpus below.
    chunks = [
        make_chunk("a", "The stall occurs when the critical angle of attack is exceeded."),
        make_chunk("b", "Weight and balance must be computed before every flight."),
    ]
    index_dir = tmp_path / "index"
    build_bm25_index(chunks, index_dir / "bm25")
    build_vector_index(chunks, index_dir / "lancedb")
    # config.yaml's real retrieval.top_n (20) exceeds this 2-chunk synthetic corpus.
    monkeypatch.setenv("RETRIEVAL__TOP_N", "2")

    result = runner.invoke(app, ["query", "--question", "What causes a stall?", "--index", str(index_dir)])

    assert result.exit_code == 0
    assert len(result.stdout.strip()) > 0
