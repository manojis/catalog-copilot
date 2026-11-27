"""Deterministic stand-ins for the ML models, so tests need no model downloads."""

import math
import re
import zlib
from collections.abc import Sequence

from catalog_copilot.db.models import EMBEDDING_DIM

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class HashingEmbedder:
    """Each word switches on one of the 384 positions, so texts sharing words point the same way.

    Not semantic ("coat" and "parka" are unrelated here), but repeatable, and it behaves like a
    real embedder where it matters: shared words -> smaller cosine distance.
    """

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    @staticmethod
    def _embed(text: str) -> list[float]:
        values = [0.0] * EMBEDDING_DIM
        for word in _words(text):
            values[zlib.crc32(word.encode()) % EMBEDDING_DIM] += 1.0
        length = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / length for v in values]


class WordOverlapReranker:
    """Scores a document by how many distinct query words it contains."""

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        query_words = set(_words(query))
        return [float(len(query_words & set(_words(doc)))) for doc in documents]
