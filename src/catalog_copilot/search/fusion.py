"""Reciprocal Rank Fusion (RRF): merge several ranked lists into one.

Each product scores 1 / (k + rank) in every list it appears in, and the scores are added:

    rank 1 -> 1/61 = 0.0164    rank 2 -> 1/62 = 0.0161    rank 50 -> 1/110 = 0.0091

Only positions are used, never the searches' own scores: ts_rank_cd and cosine distance are on
different scales and can't be added directly. A product found by both searches gets two shares,
so agreement between keyword and vector search lifts it above products only one search found.
k = 60 is the constant from the original RRF paper (Cormack et al., 2009); a larger k flattens
the gap between top and lower ranks.
"""

from collections.abc import Sequence

RRF_K = 60


def reciprocal_rank_fusion(*ranked_lists: Sequence[str], k: int = RRF_K) -> list[tuple[str, float]]:
    """(id, score) pairs, best first. Ties go to the better single rank, then to the id."""
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    for ranked in ranked_lists:
        seen: set[str] = set()
        for rank, item in enumerate(ranked, start=1):
            if item in seen:  # a repeat within one list doesn't earn a second share
                continue
            seen.add(item)
            scores[item] = scores.get(item, 0.0) + 1 / (k + rank)
            best_rank[item] = min(rank, best_rank.get(item, rank))
    return sorted(scores.items(), key=lambda pair: (-pair[1], best_rank[pair[0]], pair[0]))
