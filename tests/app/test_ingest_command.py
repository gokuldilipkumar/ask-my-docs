import pytest

from typer.testing import CliRunner

from app.main import app

runner = CliRunner()


@pytest.mark.slow
def test_ingest_command_creates_both_indexes(make_pdf, tmp_path, monkeypatch):
    pdf_path = make_pdf([[
        ("Chapter 4: Energy Management", 14, True),
        ("Total Energy", 10, True),
        ("Body text about total energy in the airplane during flight.", 10, False),
    ]])
    out_dir = tmp_path / "out"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = runner.invoke(app, ["ingest", "--pdf", str(pdf_path), "--out", str(out_dir)])

    assert result.exit_code == 0
    assert (out_dir / "bm25").exists()
    assert (out_dir / "lancedb").exists()
