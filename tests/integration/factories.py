"""Small builders for test rows."""

from decimal import Decimal
from typing import Any

from catalog_copilot.db.models import EMBEDDING_DIM, Product


def make_product(
    asin: str,
    title: str = "Test product",
    *,
    brand: str | None = "Acme",
    price: str = "10.00",
    attributes: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
    search_text: str | None = None,
) -> Product:
    return Product(
        id=asin,
        title=title,
        brand=brand,
        price=Decimal(price),
        attributes=attributes or {},
        search_text=search_text or title,
        embedding=embedding or [0.0] * EMBEDDING_DIM,
    )
