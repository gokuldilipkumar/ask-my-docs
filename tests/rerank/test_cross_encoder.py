import pytest

from config.settings import RerankConfig
from rerank import cross_encoder
from rerank.cross_encoder import rerank


def test_disabled_rerank_preserves_fused_order_and_truncates(monkeypatch):
    monkeypatch.setattr(
        cross_encoder,
        "_get_model",
        lambda name: pytest.fail("passthrough must not load the model"),
    )
    candidates = [("b", "text b"), ("a", "text a"), ("c", "text c")]
    config = RerankConfig(enabled=False, top_k=2)

    assert rerank("any query", candidates, config) == ["b", "a"]


def test_empty_candidates_return_empty_without_loading_model(monkeypatch):
    monkeypatch.setattr(
        cross_encoder,
        "_get_model",
        lambda name: pytest.fail("empty input must not load the model"),
    )
    config = RerankConfig(enabled=True, top_k=5)

    assert rerank("any query", [], config) == []
