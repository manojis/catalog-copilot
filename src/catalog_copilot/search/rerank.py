"""Rerank candidates with a cross-encoder (MiniLM).

Unlike BGE, which embeds the query and each product separately, a cross-encoder reads the query
and ONE product's text together and returns one relevance score. That is more accurate (it can
see that "warm" matches "fleece lined" in this product) but far slower, so it only rescores the
top RRF candidates, never the whole catalog.
"""

from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from fastembed.rerank.cross_encoder import TextCrossEncoder

from catalog_copilot.config import get_settings


class Reranker(Protocol):
    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """One relevance score per document, in the same order (higher = more relevant)."""
        ...


class FastEmbedReranker:
    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self._model = TextCrossEncoder(model_name, cache_dir=cache_dir)

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, documents, batch_size=64)]


@lru_cache
def get_reranker() -> FastEmbedReranker:
    settings = get_settings()
    return FastEmbedReranker(settings.reranker_model, settings.model_cache_dir)


def rerank(
    reranker: Reranker, query: str, candidates: Sequence[tuple[str, str]]
) -> list[tuple[str, float]]:
    """Score (id, text) candidates against the query; (id, score) pairs, best first.

    The text is the product's full ``search_text`` (title, brand, category, attributes and
    features): dropping the features changed 6 of the top 10 in measurements, while the longest
    texts (~240 tokens) fit MiniLM's 512-token limit. Equal scores keep the incoming RRF order.
    """
    if not candidates:
        return []
    scores = reranker.score(query, [text for _, text in candidates])
    if len(scores) != len(candidates):
        raise ValueError(f"reranker returned {len(scores)} scores for {len(candidates)} texts")
    ranked = sorted(enumerate(scores), key=lambda pair: -pair[1])  # stable: ties keep RRF order
    return [(candidates[i][0], score) for i, score in ranked]
