"""Reranking logic with a fake cross-encoder (no model download in unit tests)."""

from collections.abc import Sequence

import pytest

from catalog_copilot.search.rerank import rerank


class WordOverlapReranker:
    """Scores a document by how many query words it contains."""

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        words = set(query.lower().split())
        return [float(len(words & set(doc.lower().split()))) for doc in documents]


class BrokenReranker:
    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        return [1.0]


CANDIDATES = [  # in RRF order
    ("SOCK", "warm wool socks"),
    ("COAT", "warm winter coat fleece lined"),
    ("SHIRT", "cotton t-shirt"),
    ("PARKA", "winter parka warm"),
]


def test_best_score_first() -> None:
    ranked = rerank(WordOverlapReranker(), "warm winter coat", CANDIDATES)
    assert ranked[0] == ("COAT", 3.0)
    assert [item for item, _ in ranked] == ["COAT", "PARKA", "SOCK", "SHIRT"]


def test_equal_scores_keep_the_incoming_order() -> None:
    ranked = rerank(WordOverlapReranker(), "zzz", CANDIDATES)  # every score is 0
    assert [item for item, _ in ranked] == ["SOCK", "COAT", "SHIRT", "PARKA"]


def test_no_candidates() -> None:
    assert rerank(WordOverlapReranker(), "warm coat", []) == []


def test_score_count_mismatch_fails_loudly() -> None:
    with pytest.raises(ValueError, match="1 scores for 4 texts"):
        rerank(BrokenReranker(), "warm coat", CANDIDATES)
