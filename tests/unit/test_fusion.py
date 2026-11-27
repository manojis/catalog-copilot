"""Reciprocal Rank Fusion: merged order and scores."""

import pytest

from catalog_copilot.search.fusion import reciprocal_rank_fusion


def ids(fused: list[tuple[str, float]]) -> list[str]:
    return [item for item, _ in fused]


def test_found_by_both_beats_top_of_one() -> None:
    keyword = ["A", "B", "C"]
    vector = ["D", "C", "A"]
    fused = reciprocal_rank_fusion(keyword, vector)
    # A: 1/61 + 1/63 = 0.0323   C: 1/63 + 1/62 = 0.0320   D: 1/61 = 0.0164   B: 1/62 = 0.0161
    assert ids(fused) == ["A", "C", "D", "B"]
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 63)


def test_single_list_keeps_its_order() -> None:
    assert ids(reciprocal_rank_fusion(["X", "Y", "Z"])) == ["X", "Y", "Z"]


def test_empty_lists() -> None:
    assert reciprocal_rank_fusion() == []
    assert reciprocal_rank_fusion([], []) == []
    assert ids(reciprocal_rank_fusion([], ["A"])) == ["A"]


def test_ties_go_to_the_better_single_rank_then_id() -> None:
    # B is #1 in one list; A and C are #1 in theirs -> all score 1/61. Then by id.
    assert ids(reciprocal_rank_fusion(["B"], ["C"], ["A"])) == ["A", "B", "C"]
    # P: rank 2 + rank 2 = 2/62. Q: rank 1 + rank 3 = 1/61 + 1/63 (slightly higher).
    assert ids(reciprocal_rank_fusion(["Q", "P", "x"], ["y", "P", "Q"]))[:2] == ["Q", "P"]


def test_repeats_within_one_list_count_once() -> None:
    fused = dict(reciprocal_rank_fusion(["A", "A", "B"]))
    assert fused["A"] == pytest.approx(1 / 61)
    assert fused["B"] == pytest.approx(1 / 63)  # keeps its original position (3rd)


def test_larger_k_flattens_the_gap_between_ranks() -> None:
    gap_small_k = dict(reciprocal_rank_fusion(["A", "B"], k=1))
    gap_large_k = dict(reciprocal_rank_fusion(["A", "B"], k=600))
    assert gap_small_k["A"] / gap_small_k["B"] > gap_large_k["A"] / gap_large_k["B"]
