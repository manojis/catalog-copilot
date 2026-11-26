"""Query parser: the ParsedQuery model (rules are tested further down as they're added)."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from catalog_copilot.search.query_parser import ParsedQuery

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
