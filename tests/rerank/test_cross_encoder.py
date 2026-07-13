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


def test_rerank_loads_the_model_named_in_config(monkeypatch):
    captured = {}

    class FakeModel:
        def predict(self, pairs):
            return [0.0] * len(pairs)

    def fake_get_model(name):
        captured["name"] = name
        return FakeModel()

    monkeypatch.setattr(cross_encoder, "_get_model", fake_get_model)
    config = RerankConfig(enabled=True, model="some/other-reranker", top_k=1)

    rerank("q", [("a", "text")], config)

    assert captured["name"] == "some/other-reranker"


@pytest.mark.slow
def test_rerank_puts_semantically_relevant_candidate_first():
    # "off" contains the exact keyword but is semantically off-topic (same fixture
    # design as test_hybrid.py's weight-flip test); a cross-encoder should see
    # through it. Probe-verified against the real model at build time:
    # rel = -8.69 vs off = -9.97 (logits, higher = more relevant).
    candidates = [
        ("off", "stall stall stall invoice paperwork filing cabinet office supplies."),
        ("rel", "Exceeding the critical angle of attack makes the wing stop producing lift."),
    ]
    config = RerankConfig(enabled=True, top_k=2)

    result = rerank("What causes an aerodynamic stall?", candidates, config)

    assert result[0] == "rel"


@pytest.mark.slow
def test_rerank_truncates_to_top_k_and_handles_top_k_beyond_len():
    candidates = [
        ("a", "Exceeding the critical angle of attack makes the wing stop producing lift."),
        ("b", "Weight and balance must be computed before every flight."),
        ("c", "Radio communication procedures at towered airports."),
    ]
    query = "What causes an aerodynamic stall?"

    top2 = rerank(query, candidates, RerankConfig(enabled=True, top_k=2))
    all3 = rerank(query, candidates, RerankConfig(enabled=True, top_k=10))

    assert len(top2) == 2
    assert sorted(all3) == ["a", "b", "c"]  # top_k beyond len returns all, no error
