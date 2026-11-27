"""Attribute values shared by ingest (what we store) and the query parser (what we filter on).

Both sides must use these exact strings. If ingest stored "gray" and the parser filtered on
"grey", the filter would silently match nothing.
"""

import re
from typing import Final, Literal, get_args

Gender = Literal["women", "men", "unisex", "girls", "boys", "kids", "baby"]
GENDERS: Final[tuple[Gender, ...]] = get_args(Gender)

Color = Literal[
    "black", "white", "gray", "navy", "blue", "red", "green", "pink", "purple", "brown",
    "beige", "yellow", "orange", "gold", "silver", "khaki", "tan", "ivory", "burgundy",
    "olive", "teal", "maroon", "cream", "charcoal",
]  # fmt: skip
COLORS: Final[tuple[Color, ...]] = get_args(Color)
COLOR_ALIASES: Final[dict[str, Color]] = {"grey": "gray"}

_CANONICAL_COLOR: Final[dict[str, Color]] = {color: color for color in COLORS} | COLOR_ALIASES

# Whole words only, so "tan" doesn't match inside "tank".
COLOR_PATTERN: Final = re.compile(r"\b(" + "|".join(_CANONICAL_COLOR) + r")\b", re.IGNORECASE)


def canonical_color(word: str) -> Color | None:
    """The stored color value for a color word ("Grey" -> "gray"), or None if it isn't one."""
    return _CANONICAL_COLOR.get(word.lower())


# How shoppers write each gender, after apostrophes are removed ("women's" -> "womens").
# Plurals and possessives only: a singular "girl" or "boy" in a query is often a print or a
# style ("girl power tee", "boyfriend jeans"), not who the product is for.
GENDER_WORDS: Final[dict[str, Gender]] = {
    "women": "women", "womens": "women", "ladies": "women",
    "men": "men", "mens": "men",
    "girls": "girls",
    "boys": "boys",
    "kids": "kids", "children": "kids", "childrens": "kids",
    "baby": "baby", "babys": "baby", "infant": "baby", "infants": "baby",
    "unisex": "unisex",
}  # fmt: skip
