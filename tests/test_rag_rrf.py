from sheela.rag.hybrid import reciprocal_rank_fusion


def test_single_ranking_preserves_order():
    fused = reciprocal_rank_fusion([["a", "b", "c"]])
    order = [item for item, _ in fused]
    assert order == ["a", "b", "c"]


def test_two_rankings_merge_by_score():
    # 'y' is at the top of both; 'x' top in A but last in B; 'z' middle in both
    fused = reciprocal_rank_fusion([["x", "y", "z"], ["y", "z", "x"]])
    order = [item for item, _ in fused]
    assert order[0] == "y"  # both top, highest combined score


def test_items_in_only_one_ranking_still_appear():
    fused = reciprocal_rank_fusion([["a", "b"], ["c", "d"]])
    items = {item for item, _ in fused}
    assert items == {"a", "b", "c", "d"}


def test_scores_are_positive_and_descending():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["a", "c", "b"]])
    scores = [s for _, s in fused]
    assert all(s > 0 for s in scores)
    assert scores == sorted(scores, reverse=True)


def test_empty_rankings_returns_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []
