import pytest

from retrieval.fusion import reciprocal_rank_fusion


def test_document_ranked_first_in_both_lists_ranks_first_in_fusion():
    ranking_a = ["x", "y", "z"]
    ranking_b = ["x", "z", "y"]

    fused = reciprocal_rank_fusion([ranking_a, ranking_b], weights=[1.0, 1.0], k=60)

    assert fused[0] == "x"


def test_document_present_in_only_one_ranking_still_appears():
    ranking_a = ["x", "y"]
    ranking_b = ["z"]

    fused = reciprocal_rank_fusion([ranking_a, ranking_b], weights=[1.0, 1.0], k=60)

    assert set(fused) == {"x", "y", "z"}


def test_zero_weighting_a_ranking_makes_fusion_match_the_other_rankings_order():
    ranking_a = ["x", "y", "z"]
    ranking_b = ["z", "y", "x"]

    fused = reciprocal_rank_fusion([ranking_a, ranking_b], weights=[1.0, 0.0], k=60)

    assert fused == ["x", "y", "z"]


def test_mismatched_rankings_and_weights_lengths_raise():
    ranking_a = ["x", "y"]
    ranking_b = ["z"]

    with pytest.raises(ValueError):
        reciprocal_rank_fusion([ranking_a, ranking_b], weights=[1.0], k=60)


def test_changing_weights_changes_which_document_ranks_first():
    ranking_a = ["x", "y"]
    ranking_b = ["y", "x"]

    favor_a = reciprocal_rank_fusion([ranking_a, ranking_b], weights=[1.0, 0.1], k=60)
    favor_b = reciprocal_rank_fusion([ranking_a, ranking_b], weights=[0.1, 1.0], k=60)

    assert favor_a[0] == "x"
    assert favor_b[0] == "y"
