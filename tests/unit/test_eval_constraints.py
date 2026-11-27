"""The constraint checker itself: product checks, parse comparison and the report math."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from catalog_copilot.evals.constraints import (
    DEFAULT_DATASET,
    Case,
    Dataset,
    Expectation,
    evaluate,
    load_dataset,
    parse_differences,
    violations,
)
from catalog_copilot.search.query_parser import ParsedQuery
from catalog_copilot.search.service import SearchHit, SearchResponse

D = Decimal
ROOT = Path(__file__).resolve().parents[2]


def hit(price: str | None = "50.00", brand: str | None = "Acme", **attributes: str) -> SearchHit:
    return SearchHit(
        id="X", title="Some product", brand=brand, price=D(price) if price else None, url=None,
        attributes=attributes, rerank_score=None, keyword_rank=None, vector_rank=None,
        rrf_rank=None,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("expect", "product", "problems"),
    [
        ({"price_max": D("100"), "price_max_inclusive": False}, hit("99.99"), []),
        ({"price_max": D("100"), "price_max_inclusive": False}, hit("100.00"), ["price 100.00"]),
        ({"price_max": D("100")}, hit("100.00"), []),  # "up to" includes $100.00
        ({"price_min": D("30")}, hit(None), ["no price"]),
        ({"gender": "women"}, hit(gender="unisex"), []),  # generous rule (option A)
        ({"gender": "women"}, hit(gender="men"), ["gender 'men'"]),
        ({"gender": "women"}, hit(), ["gender None"]),
        ({"gender": "kids"}, hit(gender="girls"), []),
        ({"color": "gray"}, hit(color="gray"), []),
        ({"color": "gray"}, hit(color="black"), ["color 'black'"]),
        ({"brands": ("adidas",)}, hit(brand="adidas Originals"), []),  # brand family
        ({"brands": ("Levi's",)}, hit(brand="LEVI'S"), []),
        ({"brands": ("Nike",)}, hit(brand="Nikestore Fakes"), ["brand 'Nikestore Fakes'"]),
        ({"brands": ("Nike",)}, hit(brand=None), ["brand None"]),
        ({}, hit(brand=None, price=None), []),  # no limits: anything satisfies
    ],
)  # fmt: skip
def test_violations(expect: dict[str, Any], product: SearchHit, problems: list[str]) -> None:
    assert violations(Expectation(**expect), product) == problems


def test_parse_differences_accepts_brand_families_and_reports_misses() -> None:
    expect = Expectation(brands=("adidas",), gender="men")
    parsed_ok = ParsedQuery(brands=("adidas", "adidas Originals"), gender="men")
    assert parse_differences(expect, parsed_ok) == []
    parsed_missing = ParsedQuery(brands=("adidas",))
    assert parse_differences(expect, parsed_missing) == ["gender: expected men, got None"]


def test_parse_differences_compares_inclusiveness() -> None:
    expect = Expectation(price_max=D("100"), price_max_inclusive=False)
    assert parse_differences(expect, ParsedQuery(price_max=D("100"))) == [
        "price_max: expected 100 (excl), got 100 (incl)"
    ]


class FixedSearcher:
    """Returns canned responses, keyed by query."""

    def __init__(self, responses: dict[str, tuple[ParsedQuery, list[SearchHit]]]) -> None:
        self.responses = responses

    def search(self, query: str, limit: int = 10) -> SearchResponse:
        parsed, hits = self.responses[query]
        return SearchResponse(
            query=query, parsed=parsed, results=hits, candidates=len(hits),
            timings_ms={"total": 100.0},
        )  # fmt: skip


def test_report_math() -> None:
    under_100: dict[str, Any] = {"price_max": D("100"), "price_max_inclusive": False}
    dataset = Dataset(
        description="test",
        cases=[
            # parsed right: 2/2 products satisfy
            Case(id="ok", query="q1", expect=Expectation(**under_100)),
            # parser missed the price: 1 of 2 products is too expensive
            Case(id="missed", query="q2", expect=Expectation(**under_100)),
            # trap that wrongly created a filter; its products don't count toward satisfaction
            Case(id="trap", query="q3", expect=Expectation(), kind="trap"),
            # no results at all
            Case(id="empty", query="q4", expect=Expectation(color="red")),
        ],
    )
    searcher = FixedSearcher(
        {
            "q1": (ParsedQuery(**under_100), [hit("10.00"), hit("20.00")]),
            "q2": (ParsedQuery(), [hit("10.00"), hit("150.00")]),
            "q3": (ParsedQuery(color="black"), [hit("999.00")]),
            "q4": (ParsedQuery(color="red"), []),
        }
    )
    report = evaluate(searcher, dataset)
    assert (report.products_checked, report.products_satisfied) == (4, 3)
    assert report.constraint_satisfaction == 0.75
    assert report.parse_accuracy == 0.5  # "ok" and "empty" parsed right
    assert report.false_filters == 1
    assert report.zero_result_cases == ["empty"]
    assert not report.passed


def test_golden_dataset_is_valid() -> None:
    dataset = load_dataset(ROOT / DEFAULT_DATASET)
    assert len(dataset.cases) >= 40
    assert len({case.id for case in dataset.cases}) == len(dataset.cases)  # unique ids
    for case in dataset.cases:
        assert case.expect.has_limits == (case.kind == "constraint"), case.id
