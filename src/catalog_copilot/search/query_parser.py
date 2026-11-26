"""Split a shopper's query into hard filters and the leftover text to search on.

Hard filters become exact SQL conditions; ``semantic_text`` goes to keyword and vector search.
See docs/adr/0007-rule-based-query-parser-in-m1.md.
"""

from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from catalog_copilot.vocabulary import Color, Gender


class ParsedQuery(BaseModel):
    """The parser's output. Validation guarantees every filter can be applied safely.

    Price bounds are inclusive: a product matches when price_min <= price <= price_max.
    ``semantic_text`` may be empty (e.g. "Nike" alone): then results come from filters only.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    brands: tuple[str, ...] = ()
    price_min: Decimal | None = Field(default=None, ge=0)
    price_max: Decimal | None = Field(default=None, ge=0)
    gender: Gender | None = None
    color: Color | None = None
    semantic_text: str = ""

    @model_validator(mode="after")
    def _check_price_range(self) -> Self:
        if (
            self.price_min is not None
            and self.price_max is not None
            and self.price_min > self.price_max
        ):
            raise ValueError("price_min must not be greater than price_max")
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
