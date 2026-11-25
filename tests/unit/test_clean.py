"""Cleaning rules, one table per rule."""

from decimal import Decimal
from typing import Any

import pytest

from catalog_copilot.ingest.clean import (
    SkipRecord,
    build_category_path,
    clean_record,
    extract_color,
    extract_material,
    normalize_gender,
    normalize_text,
    parse_price,
    truncate,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (31.99, Decimal("31.99")),
        (5, Decimal("5.00")),
        ("$1,299.50", Decimal("1299.50")),
        (19.999, Decimal("20.00")),
        (None, None),
        (0, None),
        (0.01, None),  # placeholder price
        (0.999, Decimal("1.00")),  # rounds up to the minimum
        (-4.0, None),
        (25000, None),
        ("free", None),
        (True, None),
    ],
)
def test_parse_price(raw: Any, expected: Decimal | None) -> None:
    assert parse_price(raw) == expected


@pytest.mark.parametrize(
    ("department", "categories", "expected"),
    [
        ("womens", [], "women"),
        ("Womens", [], "women"),
        ("mens", [], "men"),
        ("Unisex-adult", [], "unisex"),
        ("unisex-child", [], "kids"),
        ("baby-girls", [], "baby"),
        (None, ["Clothing, Shoes & Jewelry", "Women", "Shoes"], "women"),
        (None, ["Clothing, Shoes & Jewelry", "Boys"], "boys"),
        (None, ["Clothing, Shoes & Jewelry", "Novelty & More"], None),
        ("something new", [], None),
    ],
)
def test_normalize_gender(
    department: str | None, categories: list[str], expected: str | None
) -> None:
    details = {"Department": department} if department else {}
    assert normalize_gender(details, categories) == expected


@pytest.mark.parametrize(
    ("details", "title", "expected"),
    [
        ({"Color": "Black"}, "Running Shoe", "black"),
        ({"Color": "Heather Grey"}, "Hoodie", "gray"),  # alias
        ({"Color": "Multi"}, "Navy Striped Polo", "navy"),  # unknown listed color -> title
        ({}, "Women's White Leather Sneaker", "white"),
        ({}, "Blackout Curtain Clips", None),  # whole words only
        ({}, "Plain Tee", None),
    ],
)
def test_extract_color(details: dict[str, str], title: str, expected: str | None) -> None:
    assert extract_color(details, title) == expected


def test_extract_material_uses_first_known_key_lowercased() -> None:
    assert extract_material({"Fabric Type": "Cotton", "Material": "Leather"}) == "leather"
    assert extract_material({"Fabric Type": " 90% Polyester,  10% Spandex "}) == (
        "90% polyester, 10% spandex"
    )
    assert extract_material({}) is None


def test_build_category_path_drops_root() -> None:
    cats = ["Clothing, Shoes & Jewelry", "Women", "Shoes", "Athletic", "Running"]
    assert build_category_path(cats) == "Women > Shoes > Athletic > Running"
    assert build_category_path(["Clothing, Shoes & Jewelry"]) is None


def test_normalize_text_unescapes_html_and_collapses_spaces() -> None:
    assert normalize_text("Tom &amp; Jerry\n  Tee ") == "Tom & Jerry Tee"
    assert normalize_text(None) == ""


def test_truncate_cuts_at_word_boundary() -> None:
    assert truncate("breathable mesh upper", 15) == "breathable"
    assert truncate("short", 15) == "short"


RAW = {
    "parent_asin": "B0TEST0001",
    "title": "New Balance Men's 880 V13 Wide Running Shoe",
    "price": 89.99,
    "store": "New Balance",
    "categories": ["Clothing, Shoes & Jewelry", "Men", "Shoes", "Athletic", "Running"],
    "details": {"Department": "mens", "Color": "Black/White", "Material": "Mesh"},
    "features": ["Breathable engineered mesh upper", "Fresh Foam X cushioning"],
    "description": ["A daily trainer &amp; long-run shoe."],
}


def test_clean_record_builds_full_product() -> None:
    product = clean_record(RAW)
    assert product.id == "B0TEST0001"
    assert product.price == Decimal("89.99")
    assert product.brand == "New Balance"
    assert product.category_path == "Men > Shoes > Athletic > Running"
    assert product.attributes == {"gender": "men", "color": "black", "material": "mesh"}
    assert product.description == "A daily trainer & long-run shoe."
    assert product.url == "https://www.amazon.com/dp/B0TEST0001"
    assert product.search_text == (
        "New Balance Men's 880 V13 Wide Running Shoe. Brand: New Balance. "
        "Category: Men > Shoes > Athletic > Running. Gender: men. Color: black. "
        "Material: mesh. Features: Breathable engineered mesh upper Fresh Foam X cushioning"
    )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"parent_asin": None}, "missing id"),
        ({"title": "   "}, "missing title"),
        ({"price": None}, "missing or invalid price"),
        ({"price": 0}, "missing or invalid price"),
    ],
)
def test_clean_record_skips_unusable_records(change: dict[str, Any], reason: str) -> None:
    with pytest.raises(SkipRecord, match=reason):
        clean_record({**RAW, **change})


def test_clean_record_tolerates_missing_optional_fields() -> None:
    product = clean_record({"parent_asin": "B0X", "title": "Plain Tee", "price": 9.5})
    assert product.brand is None
    assert product.category_path is None
    assert product.attributes == {}
    assert product.search_text == "Plain Tee"
