"""The shared vocabulary: ingest may only store values the query parser can filter on."""

import pytest

from catalog_copilot.ingest.clean import GENDER_BY_CATEGORY, GENDER_BY_DEPARTMENT
from catalog_copilot.vocabulary import (
    COLOR_PATTERN,
    COLORS,
    GENDER_MATCHES,
    GENDERS,
    canonical_color,
)


def test_ingest_gender_mappings_only_produce_shared_values() -> None:
    produced = set(GENDER_BY_DEPARTMENT.values()) | set(GENDER_BY_CATEGORY.values())
    assert produced <= set(GENDERS)


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("black", "black"),
        ("Navy", "navy"),
        ("grey", "gray"),  # alias -> the one stored spelling
        ("GREY", "gray"),
        ("gray", "gray"),
        ("blush", None),  # not in the vocabulary
        ("", None),
    ],
)
def test_canonical_color(word: str, expected: str | None) -> None:
    assert canonical_color(word) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Grey Wool Coat", ["Grey"]),
        ("black and white sneakers", ["black", "white"]),
        ("tank top", []),  # "tan" only as a whole word
        ("redwood hiking boots", []),
    ],
)
def test_color_pattern_matches_whole_words(text: str, expected: list[str]) -> None:
    assert COLOR_PATTERN.findall(text) == expected


def test_every_color_is_lowercase_and_unique() -> None:
    assert all(color == color.lower() for color in COLORS)
    assert len(set(COLORS)) == len(COLORS)


def test_every_gender_filter_includes_itself_and_only_known_genders() -> None:
    assert set(GENDER_MATCHES) == set(GENDERS)
    for gender, matches in GENDER_MATCHES.items():
        assert gender in matches
        assert set(matches) <= set(GENDERS)
