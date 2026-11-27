"""Split a shopper's query into hard filters and the leftover text to search on.

Hard filters become exact SQL conditions; ``semantic_text`` goes to keyword and vector search.
Rules run in order (brands, price, gender, color) and each removes the words it matched.
When a match is ambiguous, no filter is created and the words stay in ``semantic_text``:
a wrong filter hides products, while leftover words only reorder them.
See docs/adr/0007-rule-based-query-parser-in-m1.md.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from catalog_copilot.search.brands import BrandMatcher, normalize_token
from catalog_copilot.vocabulary import GENDER_WORDS, Color, Gender, canonical_color

MAX_QUERY_CHARS = 500


class ParsedQuery(BaseModel):
    """The parser's output. Validation guarantees every filter can be applied safely.

    Each price bound says whether it includes its value: "under $100" is price < 100
    (``price_max_inclusive=False``), "up to $100" is price <= 100.
    ``semantic_text`` may be empty (e.g. "Nike" alone): then results come from filters only.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    brands: tuple[str, ...] = ()
    price_min: Decimal | None = Field(default=None, ge=0)
    price_min_inclusive: bool = True
    price_max: Decimal | None = Field(default=None, ge=0)
    price_max_inclusive: bool = True
    gender: Gender | None = None
    color: Color | None = None
    semantic_text: str = ""

    @model_validator(mode="after")
    def _check_price_range(self) -> Self:
        if self.price_min is None or self.price_max is None:
            return self
        if self.price_min > self.price_max:
            raise ValueError("price_min must not be greater than price_max")
        if self.price_min == self.price_max and not (
            self.price_min_inclusive and self.price_max_inclusive
        ):
            raise ValueError("price range is empty")
        return self

    @property
    def has_filters(self) -> bool:
        return bool(
            self.brands
            or self.price_min is not None
            or self.price_max is not None
            or self.gender
            or self.color
        )

    def matches_price(self, price: Decimal) -> bool:
        """Whether a product price satisfies the price filter (the same rule the SQL applies)."""
        if self.price_min is not None and (
            price < self.price_min or (price == self.price_min and not self.price_min_inclusive)
        ):
            return False
        return self.price_max is None or not (
            price > self.price_max or (price == self.price_max and not self.price_max_inclusive)
        )


# --- price -------------------------------------------------------------------------------

_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
# A number followed by a unit isn't a price: "under 18 months", "under 5 lbs".
_NOT_A_UNIT = (
    r"(?![.,]?\d)(?!\s?(?:%|x\b|lbs?\b|pounds?\b|oz\b|ounces?\b|in\b|inch(?:es)?\b|\"|cm\b|mm\b"
    r"|ft\b|feet\b|kg\b|years?\b|yrs?\b|months?\b|mos?\b|weeks?\b|pcs?\b|pieces?\b|pack\b"
    r"|pairs?\b|k\b))"
)


def _money(name: str) -> str:
    return (
        rf"(?<![\w.$])(?P<{name}_currency>\$\s?)?(?P<{name}>{_NUMBER})"
        rf"(?:\s?(?P<{name}_word>dollars?|bucks|usd)\b)?{_NOT_A_UNIT}"
    )


_PriceKind = Literal["range", "max_exclusive", "max_inclusive", "min_exclusive", "min_inclusive"]


@dataclass(frozen=True)
class _PriceRule:
    kind: _PriceKind
    pattern: re.Pattern[str]
    # A bare number ("under 100") counts only after these words; others need "$" or "dollars".
    bare_number_ok: bool


def _rule(kind: _PriceKind, regex: str, *, bare_number_ok: bool) -> _PriceRule:
    return _PriceRule(kind, re.compile(regex, re.IGNORECASE), bare_number_ok)


_PRICE_RULES = (  # ranges first, so "$50 to $80" isn't read as two separate bounds
    _rule(
        "range",
        rf"\bbetween\s+{_money('a')}\s+(?:and|to|-)\s+{_money('b')}",
        bare_number_ok=True,
    ),
    _rule(
        "range",
        rf"(?:\bfrom\s+)?{_money('a')}\s*(?:-|–|to\b)\s*{_money('b')}",
        bare_number_ok=False,
    ),
    _rule(
        "max_exclusive",
        rf"\b(?:under|below|less\s+than|cheaper\s+than|lower\s+than)\s+{_money('a')}",
        bare_number_ok=True,
    ),
    _rule(
        "max_inclusive",
        rf"\b(?:up\s+to|at\s+most|no\s+more\s+than|max(?:imum)?(?:\s+of)?)\s+{_money('a')}",
        bare_number_ok=False,
    ),
    _rule(
        "min_exclusive",
        rf"\b(?:over|above|more\s+than|greater\s+than)\s+{_money('a')}",
        bare_number_ok=False,
    ),
    _rule(
        "min_inclusive",
        rf"\b(?:at\s+least|min(?:imum)?(?:\s+of)?|starting\s+at|from)\s+{_money('a')}",
        bare_number_ok=False,
    ),
    _rule(
        "min_inclusive",
        rf"{_money('a')}\s?(?:\+|and\s+up\b|or\s+more\b|and\s+above\b)",
        bare_number_ok=False,
    ),
)


@dataclass(frozen=True)
class _PriceRange:
    low: tuple[Decimal, bool] | None = None  # (value, inclusive)
    high: tuple[Decimal, bool] | None = None


def _has_money_marker(match: re.Match[str]) -> bool:
    names = [name for name in ("a", "b") if name in match.re.groupindex]
    return any(match.group(f"{n}_currency") or match.group(f"{n}_word") for n in names)


def _extract_price(text: str) -> tuple[_PriceRange, str]:
    bounds: list[tuple[Literal["low", "high"], Decimal, bool]] = []

    def take(rule: _PriceRule, match: re.Match[str]) -> str:
        if not rule.bare_number_ok and not _has_money_marker(match):
            return match.group(0)
        a = Decimal(match.group("a").replace(",", ""))
        if rule.kind == "range":
            bounds.append(("low", a, True))
            bounds.append(("high", Decimal(match.group("b").replace(",", "")), True))
        else:
            side: Literal["low", "high"] = "high" if rule.kind.startswith("max") else "low"
            bounds.append((side, a, rule.kind.endswith("inclusive")))
        return " "

    remaining = text
    for rule in _PRICE_RULES:
        remaining = rule.pattern.sub(lambda m, r=rule: take(r, m), remaining)  # type: ignore[misc]

    low = {(value, inclusive) for side, value, inclusive in bounds if side == "low"}
    high = {(value, inclusive) for side, value, inclusive in bounds if side == "high"}
    if len(low) > 1 or len(high) > 1:  # "under $50 under $100": which one?
        return _PriceRange(), text
    price = _PriceRange(low=next(iter(low), None), high=next(iter(high), None))
    if price.low and price.high and not _is_satisfiable(price.low, price.high):
        return _PriceRange(), text  # "between $80 and $50" or "over $100 under $50"
    return price, remaining


def _is_satisfiable(low: tuple[Decimal, bool], high: tuple[Decimal, bool]) -> bool:
    if low[0] < high[0]:
        return True
    return low[0] == high[0] and low[1] and high[1]


# --- gender and color --------------------------------------------------------------------

# "baby blue" is a color and a "baby doll" dress is women's wear: neither means gender = baby.
_NOT_GENDER_AFTER_BABY = frozenset({"blue", "pink", "doll", "dolls"})
# Phrases where a color word isn't the product's color.
_NOT_COLOR_PHRASES = frozenset(
    {("black", "friday"), ("black", "tie"), ("red", "carpet"), ("white", "noise")}
    | {("navy", "seal"), ("navy", "seals"), ("white", "collar")}
)
# "light blue": filter on blue, but keep the shade words for search.
_COLOR_MODIFIERS = frozenset(
    {"light", "dark", "pale", "bright", "baby", "hot", "royal", "sky", "neon", "deep", "rose"}
    | {"dusty", "pastel"}
)


def _extract_gender(tokens: Sequence[str]) -> tuple[Gender | None, list[str]]:
    keys = [normalize_token(token) for token in tokens]
    hits = [
        i
        for i, key in enumerate(keys)
        if key in GENDER_WORDS
        and not (key == "baby" and i + 1 < len(keys) and keys[i + 1] in _NOT_GENDER_AFTER_BABY)
    ]
    genders = {GENDER_WORDS[keys[i]] for i in hits}
    if len(genders) != 1:  # none, or "for men and women"
        return None, list(tokens)
    drop = set(hits) | {i - 1 for i in hits if i > 0 and keys[i - 1] == "for"}
    return genders.pop(), [token for i, token in enumerate(tokens) if i not in drop]


def _extract_color(tokens: Sequence[str]) -> tuple[Color | None, list[str]]:
    keys = [normalize_token(token) for token in tokens]
    hits: list[tuple[int, Color]] = []
    for i, key in enumerate(keys):
        color = canonical_color(key)
        next_key = keys[i + 1] if i + 1 < len(keys) else ""
        if color and (key, next_key) not in _NOT_COLOR_PHRASES:
            hits.append((i, color))
    colors = {color for _, color in hits}
    if len(colors) != 1:  # none, or "black and white"
        return None, list(tokens)
    drop: set[int] = set()
    for i, _ in hits:
        previous = keys[i - 1] if i > 0 else ""
        if previous in _COLOR_MODIFIERS:
            continue
        drop.add(i)
        if previous == "in":  # "dress in red"
            drop.add(i - 1)
    return colors.pop(), [token for i, token in enumerate(tokens) if i not in drop]


# --- leftover text -----------------------------------------------------------------------

_DANGLING_WORDS = frozenset({"a", "an", "and", "or", "for", "in", "with", "by", "from", "the"})


def _tidy(tokens: Sequence[str]) -> str:
    """Drop punctuation-only tokens and connector words left at either end."""
    words = [token for token in tokens if normalize_token(token)]
    while words and normalize_token(words[0]) in _DANGLING_WORDS:
        words.pop(0)
    while words and normalize_token(words[-1]) in _DANGLING_WORDS:
        words.pop()
    return " ".join(words).strip(" ,;:-")


def parse_query(query: str, brands: BrandMatcher | None = None) -> ParsedQuery:
    """Parse a shopper's query. Pass the catalog's BrandMatcher to recognize brands."""
    tokens = query[:MAX_QUERY_CHARS].replace("’", "'").split()
    found_brands: tuple[str, ...] = ()
    if brands is not None:
        found_brands, tokens = brands.extract(tokens)
    price, text = _extract_price(" ".join(tokens))
    gender, tokens = _extract_gender(text.split())
    color, tokens = _extract_color(tokens)
    return ParsedQuery(
        brands=found_brands,
        price_min=price.low[0] if price.low else None,
        price_min_inclusive=price.low[1] if price.low else True,
        price_max=price.high[0] if price.high else None,
        price_max_inclusive=price.high[1] if price.high else True,
        gender=gender,
        color=color,
        semantic_text=_tidy(tokens),
    )
