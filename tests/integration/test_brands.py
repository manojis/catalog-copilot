"""Loading the brand matcher from a real Postgres catalog."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from catalog_copilot.db.models import EMBEDDING_DIM, Product
from catalog_copilot.search.brands import load_brand_matcher

pytestmark = pytest.mark.integration


def product(asin: str, brand: str | None, title: str) -> Product:
    return Product(
        id=asin,
        title=title,
        brand=brand,
        price=Decimal("10.00"),
        attributes={},
        search_text=title,
        embedding=[0.0] * EMBEDDING_DIM,
    )


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as session:
        session.execute(delete(Product))
        session.add_all(
            [
                product("B1", "Nike", "Nike Air running shoe"),
                product("B2", "Nike", "Nike Dri-FIT tee"),
                product("B3", "Comfort", "House slipper"),
                product("B4", "Acme", "Comfort fit jeans"),
                product("B5", "Acme", "Comfort waist shorts"),
                product("B6", None, "Plain socks"),
            ]
        )
        session.commit()
        yield session
        session.execute(delete(Product))
        session.commit()


def test_load_brand_matcher_skips_everyday_words(session: Session) -> None:
    matcher = load_brand_matcher(session)
    assert matcher.extract(["nike", "comfort", "shoes"]) == (("Nike",), ["comfort", "shoes"])
