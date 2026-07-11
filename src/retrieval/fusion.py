def reciprocal_rank_fusion(
    rankings: list[list[str]], weights: list[float], k: int
) -> list[str]:
    scores: dict[str, float] = {}
    for ranking, weight in zip(rankings, weights):
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + rank)
    return sorted(scores, key=lambda doc_id: scores[doc_id], reverse=True)
