from eval.retrieval_metrics import mrr, ndcg, recall_at_k


def test_recall_at_k_counts_hits_within_top_k():
    # top_k=3 -> ["a", "b", "c"]; only "b" is in the relevant set (1 of 3 relevant ids)
    assert recall_at_k(["a", "b", "c", "d"], {"b", "d", "z"}, k=3) == 1 / 3


def test_recall_at_k_is_vacuously_perfect_with_no_relevant_docs():
    assert recall_at_k(["a", "b"], set(), k=5) == 1.0


def test_mrr_scores_by_first_hit_rank():
    assert mrr(["a", "b", "c"], {"c"}) == 1 / 3


def test_mrr_is_zero_with_no_hit():
    assert mrr(["a", "b"], {"z"}) == 0.0


def test_mrr_is_vacuously_perfect_with_no_relevant_docs():
    # Found by the Block 6 real-corpus run: q8 (deliberately out-of-scope, zero relevant
    # docs by design) scored recall_at_k=1.0, ndcg=1.0 (both vacuously-perfect) but
    # mrr=0.0 -- an inconsistent signal for the same "nothing to find" case.
    assert mrr(["a", "b"], set()) == 1.0


def test_ndcg_penalizes_lower_ranked_hits():
    perfect = ndcg(["a", "b"], {"a", "b"}, k=2)
    reversed_order = ndcg(["b", "a"], {"a"}, k=2)
    assert perfect == 1.0
    assert 0.0 < reversed_order < 1.0


def test_ndcg_is_vacuously_perfect_with_no_relevant_docs():
    assert ndcg(["a", "b"], set(), k=2) == 1.0
