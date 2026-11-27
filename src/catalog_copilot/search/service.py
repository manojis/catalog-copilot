"""The search pipeline in one call: parse -> filter -> keyword + vector -> RRF -> rerank.

"women's black running shoes under $100"
  parse_query   -> filters (women, black, < $100) + semantic_text "running shoes"
  keyword       -> top 50 ids  (full-text on search_tsv, filtered)
  vector        -> top 50 ids  (BGE query vector vs stored embeddings, filtered)
  RRF           -> one merged list
  rerank        -> MiniLM rescores the top N (default 30) -> best `limit` results
"""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session, sessionmaker

from catalog_copilot.config import get_settings
from catalog_copilot.db.models import Product
from catalog_copilot.db.session import get_engine
from catalog_copilot.embeddings import Embedder, get_embedder
from catalog_copilot.search.brands import BrandMatcher, load_brand_matcher
from catalog_copilot.search.filters import build_filters
from catalog_copilot.search.fusion import reciprocal_rank_fusion
from catalog_copilot.search.query_parser import ParsedQuery, parse_query
from catalog_copilot.search.rerank import Reranker, get_reranker, rerank
from catalog_copilot.search.retrieval import CANDIDATE_LIMIT, keyword_search, vector_search

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 10
MAX_LIMIT = CANDIDATE_LIMIT  # each search returns at most this many candidates


class SearchHit(BaseModel):
    """One result, with where it came from so rankings can be explained and evaluated."""

    id: str
    title: str
    brand: str | None
    price: Decimal | None
    url: str | None
    attributes: dict[str, Any]
    rerank_score: float | None  # None for filter-only queries (nothing to score against)
    keyword_rank: int | None  # 1-based position in each list; None if that search missed it
    vector_rank: int | None
    rrf_rank: int | None


class SearchResponse(BaseModel):
    query: str
    parsed: ParsedQuery
    results: list[SearchHit]
    candidates: int  # unique products after RRF, before reranking
    timings_ms: dict[str, float]


class _Timer:
    def __init__(self) -> None:
        self.ms: dict[str, float] = {}
        self._start = time.perf_counter()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        yield
        self.ms[name] = round((time.perf_counter() - start) * 1000, 1)

    def finish(self) -> dict[str, float]:
        self.ms["total"] = round((time.perf_counter() - self._start) * 1000, 1)
        return self.ms


class SearchService:
    """Holds the long-lived pieces (models, brand list) and runs searches with a fresh session."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        embedder: Embedder,
        reranker: Reranker,
        brands: BrandMatcher,
        rerank_candidates: int = 30,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._reranker = reranker
        self._brands = brands
        self._rerank_candidates = rerank_candidates

    def search(self, query: str, limit: int = DEFAULT_LIMIT) -> SearchResponse:
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        timer = _Timer()
        with timer.stage("parse"):
            parsed = parse_query(query, self._brands)
            filters = build_filters(parsed)

        with self._session_factory() as session:
            if parsed.semantic_text:
                hits, candidates = self._ranked_search(session, parsed, filters, limit, timer)
            elif parsed.has_filters:  # e.g. "Nike" or "women's black under $100"
                with timer.stage("filter_only"):
                    hits = self._filter_only(session, filters, limit)
                candidates = len(hits)
            else:  # empty query
                hits, candidates = [], 0

        timings = timer.finish()
        logger.info("search %r: %d results, timings_ms=%s", query, len(hits), timings)
        return SearchResponse(
            query=query, parsed=parsed, results=hits, candidates=candidates, timings_ms=timings
        )

    def _ranked_search(
        self,
        session: Session,
        parsed: ParsedQuery,
        filters: list[ColumnElement[bool]],
        limit: int,
        timer: _Timer,
    ) -> tuple[list[SearchHit], int]:
        text = parsed.semantic_text
        with timer.stage("keyword"):
            keyword_ids = keyword_search(session, text, filters)
        with timer.stage("embed"):
            query_vector = self._embedder.embed_query(text)
        with timer.stage("vector"):
            vector_ids = vector_search(session, query_vector, filters)
        with timer.stage("fuse"):
            fused = [item for item, _ in reciprocal_rank_fusion(keyword_ids, vector_ids)]

        # Score at least `limit` candidates so every returned result has been reranked.
        shortlist = fused[: max(limit, self._rerank_candidates)]
        with timer.stage("fetch"):
            rows = {
                p.id: p for p in session.scalars(select(Product).where(Product.id.in_(shortlist)))
            }
        with timer.stage("rerank"):
            # The reranker reads the leftover text, not the full query: the filters are already
            # enforced by SQL, and "under $100" would only distract it.
            ranked = rerank(self._reranker, text, [(i, rows[i].search_text) for i in shortlist])

        positions = {
            "keyword": {item: n for n, item in enumerate(keyword_ids, start=1)},
            "vector": {item: n for n, item in enumerate(vector_ids, start=1)},
            "rrf": {item: n for n, item in enumerate(fused, start=1)},
        }
        hits = [
            _hit(
                rows[item],
                rerank_score=score,
                keyword_rank=positions["keyword"].get(item),
                vector_rank=positions["vector"].get(item),
                rrf_rank=positions["rrf"].get(item),
            )
            for item, score in ranked[:limit]
        ]
        return hits, len(fused)

    @staticmethod
    def _filter_only(
        session: Session, filters: list[ColumnElement[bool]], limit: int
    ) -> list[SearchHit]:
        # Nothing to rank by meaning, so list matching products cheapest first (a stable,
        # explainable order). Popularity would be better, but the catalog has no such field yet.
        stmt = select(Product).where(*filters).order_by(Product.price, Product.id).limit(limit)
        return [
            _hit(p, rerank_score=None, keyword_rank=None, vector_rank=None, rrf_rank=None)
            for p in session.scalars(stmt)
        ]


def _hit(product: Product, **ranks: Any) -> SearchHit:
    return SearchHit(
        id=product.id,
        title=product.title,
        brand=product.brand,
        price=product.price,
        url=product.url,
        attributes=product.attributes,
        **ranks,
    )


def create_search_service(session_factory: Callable[[], Session] | None = None) -> SearchService:
    """Build the service with the real models and the catalog's brand list (run once at startup)."""
    factory = session_factory or sessionmaker(bind=get_engine())
    with factory() as session:
        brands = load_brand_matcher(session)
    return SearchService(
        session_factory=factory,
        embedder=get_embedder(),
        reranker=get_reranker(),
        brands=brands,
        rerank_candidates=get_settings().rerank_candidates,
    )
