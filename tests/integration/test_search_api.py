"""GET /search end to end: HTTP -> real pipeline on Postgres, with fake models."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from catalog_copilot.db.models import Product
from catalog_copilot.main import app, get_search_service
from catalog_copilot.search.brands import BrandMatcher
from catalog_copilot.search.service import SearchService
from tests.fakes import HashingEmbedder, WordOverlapReranker
from tests.integration.factories import make_product

pytestmark = pytest.mark.integration

EMBEDDER = HashingEmbedder()


def product(asin: str, title: str, price: str, **attributes: str) -> Product:
    return make_product(
        asin, title, brand="Acme", price=price, attributes=attributes,
        embedding=EMBEDDER.embed_query(title),
    )  # fmt: skip


@pytest.fixture(scope="module")
def client(migrated_engine: Engine) -> Iterator[TestClient]:
    with Session(migrated_engine) as session:
        session.execute(delete(Product))
        session.add_all(
            [
                product("COAT", "Warm winter coat", "80.00", gender="women"),
                product("PARKA", "Winter parka warm", "150.00", gender="men"),
                product("SOCKS", "Warm wool socks", "15.00", gender="unisex"),
                product("TEE", "Cotton t-shirt", "100.00"),
            ]
        )
        session.commit()
    service = SearchService(
        session_factory=sessionmaker(bind=migrated_engine),
        embedder=EMBEDDER,
        reranker=WordOverlapReranker(),
        brands=BrandMatcher(["Acme"]),
    )
    app.dependency_overrides[get_search_service] = lambda: service
    yield TestClient(app)
    app.dependency_overrides.clear()
    with Session(migrated_engine) as session:
        session.execute(delete(Product))
        session.commit()


def test_under_100_really_means_under_100(client: TestClient) -> None:
    body = client.get("/search", params={"q": "warm winter coat under $100"}).json()
    assert body["parsed"]["price_max"] == "100"
    assert body["parsed"]["price_max_inclusive"] is False
    ids = [hit["id"] for hit in body["results"]]
    assert ids[0] == "COAT"
    assert "PARKA" not in ids  # $150
    assert all(Decimal(hit["price"]) < 100 for hit in body["results"])


def test_womens_includes_unisex(client: TestClient) -> None:
    body = client.get("/search", params={"q": "warm for women"}).json()
    assert {hit["id"] for hit in body["results"]} == {"COAT", "SOCKS"}


def test_timings_are_reported(client: TestClient) -> None:
    body = client.get("/search", params={"q": "warm coat"}).json()
    assert body["timings_ms"]["total"] > 0
