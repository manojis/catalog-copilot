"""Recognize catalog brand names in a shopper's query.

The catalog has ~12K "brands" (mostly Amazon store names), and many are everyday words
("Comfort", "Mini", "Polo"). A brand name is only matched when it mostly refers to that brand:
other brands' titles must not use it more often than the brand has products of its own.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_copilot.db.models import Product
from catalog_copilot.vocabulary import COLOR_ALIASES, COLORS, GENDER_WORDS

BrandKey = tuple[str, ...]

# Store names that aren't brands a shopper would ask for.
NOT_BRANDS = frozenset({"generic", "unbranded", "unbrands", "unknown", "none", "na", "other"})
# Words other parser rules own. A brand made only of these words is never matched.
RESERVED_WORDS = frozenset(
    {*COLORS, *COLOR_ALIASES, *GENDER_WORDS}
    | {"under", "over", "below", "above", "between", "cheap", "max", "min"}
    | {"a", "an", "and", "or", "the", "for", "with", "by", "from", "in", "of"}
)
# "shoes by Nike" -> drop "by" together with the brand.
WORDS_BEFORE_BRAND = frozenset({"by", "from"})

_EDGE_PUNCTUATION = re.compile(r"^[^\w$]+|[^\w$+]+$")


def normalize_token(token: str) -> str:
    """Lowercase, drop apostrophes ("Levi's" -> "levis"), strip edge punctuation ("Nike,")."""
    return _EDGE_PUNCTUATION.sub("", token.lower().replace("’", "").replace("'", ""))


def brand_key(name: str) -> BrandKey:
    return tuple(token for token in map(normalize_token, name.split()) if token)


def _is_matchable(key: BrandKey) -> bool:
    if all(token in RESERVED_WORDS or token in NOT_BRANDS or token.isdigit() for token in key):
        return False
    return not (len(key) == 1 and len(key[0]) < 2)


class BrandMatcher:
    """Finds brand names in query tokens, longest name first.

    A matched brand also covers catalog brands that start with it ("adidas" also matches
    "adidas Originals"): including a related brand only adds results, missing one hides them.
    """

    def __init__(self, brands: Iterable[str]) -> None:
        spellings: dict[BrandKey, dict[str, str]] = defaultdict(dict)  # key -> lower -> name
        for name in brands:
            key = brand_key(name)
            if key and _is_matchable(key):
                spellings[key].setdefault(name.lower(), name)

        keys_by_first_word: dict[str, list[BrandKey]] = defaultdict(list)
        for key in spellings:
            keys_by_first_word[key[0]].append(key)

        self._families: dict[BrandKey, tuple[str, ...]] = {}
        for key in spellings:
            names = {
                lower: name
                for other in keys_by_first_word[key[0]]
                if other[: len(key)] == key
                for lower, name in spellings[other].items()
            }
            self._families[key] = tuple(sorted(names.values(), key=str.lower))
        self._max_words = max(map(len, spellings), default=0)

    def __len__(self) -> int:
        return len(self._families)

    def extract(self, tokens: Sequence[str]) -> tuple[tuple[str, ...], list[str]]:
        """Return (catalog brand names found, the tokens that remain)."""
        keys = [normalize_token(token) for token in tokens]
        found: dict[str, str] = {}
        remaining: list[str] = []
        i = 0
        while i < len(tokens):
            for length in range(min(self._max_words, len(tokens) - i), 0, -1):
                family = self._families.get(tuple(keys[i : i + length]))
                if family:
                    found.update((name.lower(), name) for name in family)
                    if remaining and normalize_token(remaining[-1]) in WORDS_BEFORE_BRAND:
                        remaining.pop()
                    i += length
                    break
            else:
                remaining.append(tokens[i])
                i += 1
        return tuple(found.values()), remaining


def unambiguous_brands(products: Iterable[tuple[str | None, str]]) -> list[str]:
    """Brand names (from (brand, title) rows) that mostly refer to that brand.

    "Comfort" (2 products) appears in 453 other titles, so it's an everyday word, not a brand
    the shopper means. "Nike" (97 products) appears in none.
    """
    rows = list(products)
    own: Counter[BrandKey] = Counter()
    names: dict[BrandKey, set[str]] = defaultdict(set)
    for brand, _ in rows:
        if brand and (key := brand_key(brand)):
            own[key] += 1
            names[key].add(brand)

    max_words = max(map(len, own), default=0)
    mentioned_by_others: Counter[BrandKey] = Counter()
    for brand, title in rows:
        own_key = brand_key(brand) if brand else ()
        words = brand_key(title)
        phrases = {
            words[i : i + n] for n in range(1, max_words + 1) for i in range(len(words) - n + 1)
        }
        for key in phrases & own.keys():
            if key != own_key:
                mentioned_by_others[key] += 1

    return sorted(
        name for key in own if mentioned_by_others[key] <= own[key] for name in names[key]
    )


def load_brand_matcher(session: Session) -> BrandMatcher:
    """Build the matcher from the catalog. Run once at startup (~1 s at 30K products)."""
    rows = session.execute(select(Product.brand, Product.title))
    return BrandMatcher(unambiguous_brands(rows))
