"""Text embeddings with BGE-small (fastembed, local ONNX). Used by ingest and by search."""

from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from fastembed import TextEmbedding

from catalog_copilot.config import get_settings


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self._model = TextEmbedding(model_name, cache_dir=cache_dir)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.passage_embed(texts, batch_size=64)
        return [[float(x) for x in vector] for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        # BGE adds a "search query" instruction prefix to queries, not to documents.
        return [float(x) for x in next(iter(self._model.query_embed(text)))]


@lru_cache
def get_embedder() -> FastEmbedEmbedder:
    settings = get_settings()
    return FastEmbedEmbedder(settings.embedding_model, settings.model_cache_dir)
