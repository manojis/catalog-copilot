"""The HTTP layer of GET /search, with a stub service (no database, no models)."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from catalog_copilot.main import app, get_search_service
from catalog_copilot.search.query_parser import ParsedQuery
from catalog_copilot.search.service import SearchHit, SearchResponse


class StubSearchService:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int = 10) -> SearchResponse:
        self.calls.append((query, limit))
        if self.fail:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        hit = SearchHit(
            id="B0TEST", title="Warm winter coat", brand="Acme", price=Decimal("57.98"),
            url="https://www.amazon.com/dp/B0TEST", attributes={"gender": "women"},
            rerank_score=8.11, keyword_rank=2, vector_rank=6, rrf_rank=1,
        )  # fmt: skip
        return SearchResponse(
            query=query,
            parsed=ParsedQuery(semantic_text=query),
            results=[hit],
            candidates=82,
            timings_ms={"total": 300.0},
        )


@pytest.fixture
def stub() -> Iterator[StubSearchService]:
    service = StubSearchService()
    app.dependency_overrides[get_search_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


client = TestClient(app)  # no `with`: the real lifespan (models, database) doesn't run


def test_returns_the_service_response_as_json(stub: StubSearchService) -> None:
    response = client.get("/search", params={"q": "warm winter coat", "limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "warm winter coat"
    assert body["results"][0]["id"] == "B0TEST"
    assert body["results"][0]["price"] == "57.98"  # money as a string: no float rounding
    assert body["candidates"] == 82
    assert stub.calls == [("warm winter coat", 5)]


def test_default_limit_is_10(stub: StubSearchService) -> None:
    client.get("/search", params={"q": "coat"})
    assert stub.calls == [("coat", 10)]


@pytest.mark.parametrize(
    "params",
    [
        {},  # q missing
        {"q": ""},
        {"q": "x" * 501},  # longer than the parser reads
        {"q": "coat", "limit": 0},
        {"q": "coat", "limit": 51},
        {"q": "coat", "limit": "ten"},
    ],
)
def test_invalid_parameters_are_rejected_before_searching(
    stub: StubSearchService, params: dict[str, str | int]
) -> None:
    response = client.get("/search", params=params)
    assert response.status_code == 422
    assert stub.calls == []


def test_database_outage_returns_503_without_internals() -> None:
    app.dependency_overrides[get_search_service] = lambda: StubSearchService(fail=True)
    try:
        response = client.get("/search", params={"q": "coat"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]
    assert "connection refused" not in response.text


def test_search_is_documented_in_openapi() -> None:
    schema = client.get("/openapi.json").json()
    params = {p["name"] for p in schema["paths"]["/search"]["get"]["parameters"]}
    assert params == {"q", "limit"}
