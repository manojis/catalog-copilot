"""Query parser: the ParsedQuery model, then the parsing rules (one table row per query)."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from catalog_copilot.search.brands import BrandMatcher
from catalog_copilot.search.query_parser import MAX_QUERY_CHARS, ParsedQuery, parse_query

D = Decimal

# --- ParsedQuery validation -------------------------------------------------------------


def test_defaults_mean_no_filters() -> None:
    parsed = ParsedQuery()
    assert parsed.semantic_text == ""
    assert not parsed.has_filters


def test_valid_query_with_every_filter() -> None:
    parsed = ParsedQuery(
        brands=("Nike",),
        price_min=Decimal("50"),
        price_max=Decimal("100"),
        gender="women",
        color="black",
        semantic_text="  running shoes  ",
    )
    assert parsed.has_filters
    assert parsed.semantic_text == "running shoes"  # whitespace stripped


def test_equal_price_bounds_are_allowed() -> None:
    assert ParsedQuery(price_min=Decimal("40"), price_max=Decimal("40")).has_filters


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"price_max": Decimal("-5")}, "negative price"),
        ({"price_min": Decimal("100"), "price_max": Decimal("50")}, "min greater than max"),
        ({"gender": "woman"}, "gender outside the shared vocabulary"),
        ({"color": "grey"}, "alias instead of the stored spelling"),
        ({"color": "blush"}, "color outside the shared vocabulary"),
        ({"size": "10"}, "unknown field"),
    ],
)
def test_invalid_values_are_rejected(fields: dict[str, Any], reason: str) -> None:
    with pytest.raises(ValidationError):
        ParsedQuery(**fields)


def test_is_immutable() -> None:
    parsed = ParsedQuery(color="red")
    with pytest.raises(ValidationError):
        parsed.color = "blue"


def test_exclusive_bounds_cannot_meet() -> None:
    with pytest.raises(ValidationError):
        ParsedQuery(price_min=Decimal("50"), price_max=Decimal("50"), price_max_inclusive=False)


@pytest.mark.parametrize(
    ("fields", "price", "expected"),
    [
        ({"price_max": D("100"), "price_max_inclusive": False}, "99.99", True),  # under $100
        ({"price_max": D("100"), "price_max_inclusive": False}, "100.00", False),
        ({"price_max": D("100")}, "100.00", True),  # up to $100
        ({"price_min": D("50"), "price_min_inclusive": False}, "50.00", False),  # over $50
        ({"price_min": D("50")}, "50.00", True),  # at least $50
        ({"price_min": D("50"), "price_max": D("80")}, "80.00", True),  # $50-$80
        ({}, "12345.00", True),  # no price filter
    ],
)
def test_matches_price(fields: dict[str, Any], price: str, expected: bool) -> None:
    assert ParsedQuery(**fields).matches_price(D(price)) is expected


# --- parse_query: one row per query ------------------------------------------------------

BRANDS = BrandMatcher(
    [
        "Nike", "NIKE", "Under Armour", "adidas", "adidas Originals", "Levi's", "New Balance",
        "Calvin Klein", "Generic", "Black", "Women", "X",
    ]
)  # fmt: skip
UNDER_100 = {"price_max": D("100"), "price_max_inclusive": False}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # plain text, no filters
        ("running shoes", {"semantic_text": "running shoes"}),
        ("", {}),
        ("cheap jacket", {"semantic_text": "cheap jacket"}),  # vague: no price guess
        # everything at once
        (
            "women's black Nike running shoes under $100",
            {"brands": ("Nike",), **UNDER_100, "gender": "women", "color": "black",
             "semantic_text": "running shoes"},
        ),
        # brands
        ("Under Armour hoodie", {"brands": ("Under Armour",), "semantic_text": "hoodie"}),
        (
            "under armour hoodie under $50",
            {"brands": ("Under Armour",), "price_max": D("50"), "price_max_inclusive": False,
             "semantic_text": "hoodie"},
        ),
        ("adidas sneakers", {"brands": ("adidas", "adidas Originals"),
                             "semantic_text": "sneakers"}),
        ("adidas originals sneakers", {"brands": ("adidas Originals",),
                                       "semantic_text": "sneakers"}),
        ("levis jeans", {"brands": ("Levi's",), "semantic_text": "jeans"}),
        ("Levi's 501 jeans", {"brands": ("Levi's",), "semantic_text": "501 jeans"}),
        ("jeans by levi's", {"brands": ("Levi's",), "semantic_text": "jeans"}),
        (
            "nike and adidas shoes",
            {"brands": ("Nike", "adidas", "adidas Originals"), "semantic_text": "shoes"},
        ),
        ("Nike", {"brands": ("Nike",)}),  # filters only, nothing left to search
        ("generic t-shirt", {"semantic_text": "generic t-shirt"}),  # not a real brand
        ("black dress", {"color": "black", "semantic_text": "dress"}),  # color, not brand Black
        ("women's coat", {"gender": "women", "semantic_text": "coat"}),  # gender, not brand Women
        # price
        ("jacket under 100", {**UNDER_100, "semantic_text": "jacket"}),
        ("jacket below $80", {"price_max": D("80"), "price_max_inclusive": False,
                              "semantic_text": "jacket"}),
        ("coat less than 80 dollars", {"price_max": D("80"), "price_max_inclusive": False,
                                       "semantic_text": "coat"}),
        ("up to $60 sandals", {"price_max": D("60"), "semantic_text": "sandals"}),
        ("watch over $200", {"price_min": D("200"), "price_min_inclusive": False,
                             "semantic_text": "watch"}),
        ("boots at least $30", {"price_min": D("30"), "semantic_text": "boots"}),
        ("$50+ sneakers", {"price_min": D("50"), "semantic_text": "sneakers"}),
        ("sneakers $50 and up", {"price_min": D("50"), "semantic_text": "sneakers"}),
        ("$50-$80 dress", {"price_min": D("50"), "price_max": D("80"), "semantic_text": "dress"}),
        ("dress from $50 to 80", {"price_min": D("50"), "price_max": D("80"),
                                  "semantic_text": "dress"}),
        ("dress between 50 and 80", {"price_min": D("50"), "price_max": D("80"),
                                     "semantic_text": "dress"}),
        (
            "jacket over $50 under $100",
            {"price_min": D("50"), "price_min_inclusive": False, **UNDER_100,
             "semantic_text": "jacket"},
        ),
        ("watch under $1,000", {"price_max": D("1000"), "price_max_inclusive": False,
                                "semantic_text": "watch"}),
        ("tee under $19.99", {"price_max": D("19.99"), "price_max_inclusive": False,
                              "semantic_text": "tee"}),
        # price traps: conflicting or not about price, so no filter and the text stays
        ("dress between $80 and $50", {"semantic_text": "dress between $80 and $50"}),
        ("coat under $50 under $100", {"semantic_text": "coat under $50 under $100"}),
        ("size 10 boots", {"semantic_text": "size 10 boots"}),
        ("pack of 3 socks", {"semantic_text": "pack of 3 socks"}),
        ("8-10 boots", {"semantic_text": "8-10 boots"}),
        ("up to 60 sandals", {"semantic_text": "up to 60 sandals"}),
        ("over 50 t-shirt", {"semantic_text": "over 50 t-shirt"}),
        (
            "baby onesie under 18 months",
            {"gender": "baby", "semantic_text": "onesie under 18 months"},
        ),
        # gender
        ("men's boots", {"gender": "men", "semantic_text": "boots"}),
        ("mens boots", {"gender": "men", "semantic_text": "boots"}),
        ("boots for women", {"gender": "women", "semantic_text": "boots"}),  # not "men"
        ("ladies blouse", {"gender": "women", "semantic_text": "blouse"}),
        ("girls' party dress", {"gender": "girls", "semantic_text": "party dress"}),
        ("kids rain boots", {"gender": "kids", "semantic_text": "rain boots"}),
        ("shoes for men and women", {"semantic_text": "shoes for men and women"}),
        ("boyfriend jeans", {"semantic_text": "boyfriend jeans"}),
        ("baby doll dress", {"semantic_text": "baby doll dress"}),
        # color
        ("grey hoodie", {"color": "gray", "semantic_text": "hoodie"}),
        ("tan boots", {"color": "tan", "semantic_text": "boots"}),
        ("tank top", {"semantic_text": "tank top"}),
        ("dress in red", {"color": "red", "semantic_text": "dress"}),
        ("light blue shirt", {"color": "blue", "semantic_text": "light blue shirt"}),
        ("baby blue dress", {"color": "blue", "semantic_text": "baby blue dress"}),
        (
            "black friday white sneakers",
            {"color": "white", "semantic_text": "black friday sneakers"},
        ),
        ("black and white sneakers", {"semantic_text": "black and white sneakers"}),
    ],
)  # fmt: skip
def test_parse_query(query: str, expected: dict[str, Any]) -> None:
    assert parse_query(query, BRANDS) == ParsedQuery(**expected)


def test_parse_query_without_brand_matcher_treats_brands_as_text() -> None:
    assert parse_query("Nike running shoes") == ParsedQuery(semantic_text="Nike running shoes")


def test_very_long_query_is_truncated() -> None:
    parsed = parse_query("shoes " * 1000)
    assert len(parsed.semantic_text) <= MAX_QUERY_CHARS
