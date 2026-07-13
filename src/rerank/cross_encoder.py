from sentence_transformers import CrossEncoder

from config.settings import RerankConfig

# keyed by model name because the reranker is config-swappable
_models: dict[str, CrossEncoder] = {}


def _get_model(model_name: str) -> CrossEncoder:
    if model_name not in _models:
        _models[model_name] = CrossEncoder(model_name, device="cpu")
    return _models[model_name]


def rerank(query: str, candidates: list[tuple[str, str]], config: RerankConfig) -> list[str]:
    ids = [cid for cid, _ in candidates]
    if not config.enabled or not candidates:
        return ids[: config.top_k]
    model = _get_model(config.model)
    scores = model.predict([(query, text) for _, text in candidates])
    ranked = sorted(zip(ids, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    return [cid for cid, _ in ranked[: config.top_k]]
