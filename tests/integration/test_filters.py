"""Filters against a real Postgres: each case lists exactly which products must qualify."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from catalog_copilot.db.models import Product
from catalog_copilot.search.filters import build_filters
from catalog_copilot.search.query_parser import ParsedQuery
from tests.integration.factories import make_product

pytestmark = pytest.mark.integration

D = Decimal


def product(asin: str, brand: str | None, price: str, **attributes: str) -> Product:
    return make_product(asin, brand=brand, price=price, attributes=attributes)


PRODUCTS = [
    product("P1", "Nike", "99.99", gender="women", color="black"),
    product("P2", "NIKE", "100.00", gender="men", color="black"),
    product("P3", "adidas", "50.00", gender="unisex", color="white"),
    product("P4", "Levi's", "80.00", gender="girls"),
    product("P5", "Acme", "20.00", gender="kids", color="red"),
    product("P6", None, "5.00"),  # no brand, gender or color
    product("P7", "Acme", "30.00", gender="baby"),
]
ALL = {p.id for p in PRODUCTS}


@pytest.fixture(scope="module")
def session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as session:
        session.execute(delete(Product))
        session.add_all(PRODUCTS)
        session.commit()
        yield session
        session.execute(delete(Product))
        session.commit()


@pytest.mark.parametrize(
    ("fields", "expected_ids"),
    [
        ({}, ALL),  # no filters
        # price: "under $100" excludes exactly $100.00, "up to $100" includes it
        ({"price_max": D("100"), "price_max_inclusive": False}, ALL - {"P2"}),
        ({"price_max": D("100")}, ALL),
        ({"price_min": D("50"), "price_min_inclusive": False}, {"P1", "P2", "P4"}),
        ({"price_min": D("50"), "price_max": D("80")}, {"P3", "P4"}),
        # brand: case-insensitive, and the apostrophe is kept as stored
        ({"brands": ("Nike",)}, {"P1", "P2"}),
        ({"brands": ("Levi's", "adidas")}, {"P3", "P4"}),
        # gender (option A): unisex fits women and men; kids covers girls and boys
        ({"gender": "women"}, {"P1", "P3"}),
        ({"gender": "men"}, {"P2", "P3"}),
        ({"gender": "kids"}, {"P4", "P5"}),
        ({"gender": "girls"}, {"P4", "P5"}),
        ({"gender": "baby"}, {"P7"}),
        # color: exact stored value; products without a color never match
        ({"color": "black"}, {"P1", "P2"}),
        # everything together is AND
        (
            {"brands": ("Nike",), "color": "black", "gender": "women",
             "price_max": D("100"), "price_max_inclusive": False},
            {"P1"},
        ),
    ],
)  # fmt: skip
def test_build_filters(session: Session, fields: dict[str, Any], expected_ids: set[str]) -> None:
    parsed = ParsedQuery(**fields)
    ids = set(session.scalars(select(Product.id).where(*build_filters(parsed))))
    assert ids == expected_ids


def test_values_are_bound_parameters_not_sql_text() -> None:
    parsed = ParsedQuery(brands=("x'); DROP TABLE products; --",))
    sql = str(select(Product.id).where(*build_filters(parsed)))
    assert "DROP TABLE" not in sql
