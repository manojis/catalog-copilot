"""The whole search pipeline against a real Postgres, with fake models (tests/fakes.py)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from catalog_copilot.db.models import Product
from catalog_copilot.search.brands import BrandMatcher
from catalog_copilot.search.service import SearchHit, SearchService
from tests.fakes import HashingEmbedder, WordOverlapReranker
from tests.integration.factories import make_product

pytestmark = pytest.mark.integration

EMBEDDER = HashingEmbedder()


def product(asin: str, title: str, brand: str, price: str, **attributes: str) -> Product:
    return make_product(
        asin,
        title,
        brand=brand,
        price=price,
        attributes=attributes,
        embedding=EMBEDDER.embed_query(title),
    )


PRODUCTS = [
    product(
        "COAT", "Warm winter coat fleece lined", "Acme", "80.00", gender="women", color="black"
    ),
    product("PARKA", "Winter parka warm", "Nike", "150.00", gender="men"),
    product("SOCKS", "Warm wool socks", "Nike", "15.00", gender="unisex"),
    product("RAIN", "Rain jacket", "Acme", "60.00", gender="women"),
    product("SHOES", "Running shoes", "Nike", "90.00", gender="women", color="black"),
    product("TEE", "Cotton t-shirt", "Acme", "10.00"),
]


@pytest.fixture(scope="module")
def service(migrated_engine: Engine) -> Iterator[SearchService]:
    with Session(migrated_engine) as session:
        session.execute(delete(Product))
        session.add_all(PRODUCTS)
        session.commit()
    yield SearchService(
        session_factory=sessionmaker(bind=migrated_engine),
        embedder=EMBEDDER,
        reranker=WordOverlapReranker(),
        brands=BrandMatcher(["Nike", "Acme"]),
        rerank_candidates=5,
    )
    with Session(migrated_engine) as session:
        session.execute(delete(Product))
        session.commit()


def ids(results: list[SearchHit]) -> list[str]:
    return [hit.id for hit in results]


def test_ranked_search_respects_filters_and_reranks(service: SearchService) -> None:
    response = service.search("warm winter coat under $100")
    assert response.parsed.semantic_text == "warm winter coat"
    assert response.results[0].id == "COAT"  # all three words
    assert "PARKA" not in ids(response.results)  # $150: filtered out before ranking
    assert all(response.parsed.matches_price(hit.price) for hit in response.results if hit.price)
    top = response.results[0]
    assert top.rerank_score == 3.0
    assert top.keyword_rank == 1 and top.vector_rank == 1 and top.rrf_rank == 1


def test_filter_only_query_lists_matches_cheapest_first(service: SearchService) -> None:
    response = service.search("Nike")
    assert ids(response.results) == ["SOCKS", "SHOES", "PARKA"]
    assert all(hit.rerank_score is None for hit in response.results)


def test_filter_only_with_several_filters(service: SearchService) -> None:
    # women includes unisex (SOCKS), but SOCKS isn't black; PARKA is men's.
    assert ids(service.search("women's black under $100").results) == ["COAT", "SHOES"]


def test_empty_query_returns_nothing(service: SearchService) -> None:
    response = service.search("   ")
    assert response.results == [] and response.candidates == 0


def test_no_product_passes_the_filters(service: SearchService) -> None:
    assert service.search("warm coat over $500").results == []


def test_limit(service: SearchService) -> None:
    assert len(service.search("warm", limit=1).results) == 1
    with pytest.raises(ValueError, match="between 1 and 50"):
        service.search("warm", limit=51)


def test_limit_above_rerank_candidates_still_reranks_every_result(service: SearchService) -> None:
    # rerank_candidates is 5 here; asking for 6 must score 6, not return unscored extras.
    results = service.search("warm winter coat rain jacket socks shoes t-shirt", limit=6).results
    assert len(results) == 6
    assert all(hit.rerank_score is not None for hit in results)


def test_timings_cover_every_stage(service: SearchService) -> None:
    timings = service.search("warm winter coat").timings_ms
    stages = {"parse", "keyword", "embed", "vector", "fuse", "fetch", "rerank", "total"}
    assert set(timings) == stages
