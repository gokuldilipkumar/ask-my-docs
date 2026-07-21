import pytest

from typer.testing import CliRunner

from app.main import app

runner = CliRunner()

MINIMAL_CONFIG = "chunking:\n  min_tokens: 400\n  max_tokens: 600\n  overlap_pct: 0.15\n"


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    # keep the CLI from reading the repo's config.yaml (whose corpus-specific
    # body page range would filter synthetic test PDFs down to nothing)
    (tmp_path / "config.yaml").write_text(MINIMAL_CONFIG)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


@pytest.mark.slow
def test_ingest_command_creates_both_indexes(make_pdf, tmp_path, isolated_config):
    pdf_path = make_pdf([[
        ("Chapter 4: Energy Management", 14, True),
        ("Total Energy", 10, True),
        ("Body text about total energy in the airplane during flight.", 10, False),
    ]])
    out_dir = tmp_path / "out"

    result = runner.invoke(app, ["ingest", "--pdf", str(pdf_path), "--out", str(out_dir)])

    assert result.exit_code == 0
    assert (out_dir / "bm25").exists()
    assert (out_dir / "lancedb").exists()
    assert (out_dir / "chunk_metadata.json").exists()


@pytest.mark.slow
def test_ingest_command_applies_configured_body_page_range(make_pdf, tmp_path, isolated_config, monkeypatch):
    pdf_path = make_pdf([
        [
            ("Chapter 4: Energy Management", 14, True),
            ("Total Energy", 10, True),
            ("Body text about total energy in the airplane.", 10, False),
        ],
        [
            ("Kinetic Energy", 10, True),
            ("Body text about kinetic energy during flight.", 10, False),
        ],
    ])
    out_dir = tmp_path / "out"
    monkeypatch.setenv("CHUNKING__BODY_PAGE_END", "0")

    result = runner.invoke(app, ["ingest", "--pdf", str(pdf_path), "--out", str(out_dir)])

    assert result.exit_code == 0
    assert "Ingested 1 chunks" in result.stdout  # page 1's section was filtered out
