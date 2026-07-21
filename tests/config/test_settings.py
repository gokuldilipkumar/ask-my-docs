import pytest
from pydantic import ValidationError

from config.settings import Settings


def test_loads_chunking_defaults_from_yaml(tmp_path, monkeypatch):
    yaml_content = """
chunking:
  min_tokens: 400
  max_tokens: 600
  overlap_pct: 0.15
"""
    (tmp_path / "config.yaml").write_text(yaml_content)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    settings = Settings()

    assert settings.chunking.min_tokens == 400
    assert settings.chunking.max_tokens == 600
    assert settings.chunking.overlap_pct == 0.15


def test_body_page_range_defaults_to_whole_document(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("chunking:\n  min_tokens: 400\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    settings = Settings()

    assert settings.chunking.body_page_start == 0
    assert settings.chunking.body_page_end is None


def test_missing_required_secret_raises_validation_error(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("chunking:\n  min_tokens: 400\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings()


def test_env_var_overrides_yaml_value(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("retrieval:\n  rrf_k: 60\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("RETRIEVAL__RRF_K", "30")

    settings = Settings()

    assert settings.retrieval.rrf_k == 30


def test_rerank_max_length_defaults_to_none(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("chunking:\n  min_tokens: 400\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    settings = Settings()

    assert settings.rerank.max_length is None


def test_rerank_max_length_loads_from_yaml(tmp_path, monkeypatch):
    yaml_content = "rerank:\n  max_length: 256\n"
    (tmp_path / "config.yaml").write_text(yaml_content)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    settings = Settings()

    assert settings.rerank.max_length == 256
