"""Brand matching: which names count as brands, and how they're found in a query."""

import pytest

from catalog_copilot.search.brands import BrandMatcher, normalize_token, unambiguous_brands


@pytest.mark.parametrize(
    ("token", "expected"),
    [("Levi's", "levis"), ("Nike,", "nike"), ("WOMEN’S", "womens"), ("$100", "$100"),
     ("$50+", "$50+"), ("&", ""), ("t-shirt", "t-shirt")],
)  # fmt: skip
def test_normalize_token(token: str, expected: str) -> None:
    assert normalize_token(token) == expected


def test_reserved_and_placeholder_names_are_never_brands() -> None:
    matcher = BrandMatcher(["Generic", "Black", "Women", "Under", "X", "925", "Black White"])
    assert len(matcher) == 0


def test_brand_family_includes_longer_names_that_start_with_it() -> None:
    matcher = BrandMatcher(["Calvin Klein", "Calvin Klein Jeans", "Calvin"])
    assert matcher.extract(["calvin", "klein", "jeans"]) == (("Calvin Klein Jeans",), [])
    assert matcher.extract(["calvin", "klein", "dress"]) == (
        ("Calvin Klein", "Calvin Klein Jeans"),
        ["dress"],
    )


def test_spellings_that_differ_only_by_case_appear_once() -> None:
    assert BrandMatcher(["Nike", "NIKE", "nike"]).extract(["NIKE"]) == (("Nike",), [])


def test_unambiguous_brands_skips_everyday_words() -> None:
    rows = [
        ("Nike", "Nike Air Zoom running shoe"),
        ("Comfort", "Slipper"),
        ("Acme", "Comfort fit jeans"),
        ("Acme", "Comfort waist shorts"),
        (None, "Unbranded tee"),
    ]
    # "Comfort": 1 product of its own, used in 2 other titles -> everyday word.
    assert unambiguous_brands(rows) == ["Acme", "Nike"]
