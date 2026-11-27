"""Vector search against a real Postgres + pgvector, with hand-made vectors of known distance."""

import math
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from catalog_copilot.db.models import EMBEDDING_DIM, Product
from catalog_copilot.search.filters import build_filters
from catalog_copilot.search.query_parser import ParsedQuery
from catalog_copilot.search.retrieval import vector_search
from tests.integration.factories import make_product

pytestmark = pytest.mark.integration


def vector(**weights: float) -> list[float]:
    """A length-1 vector built from named axes, e.g. vector(x=1, y=1) points between x and y."""
    axes = {"x": 0, "y": 1}
    values = [0.0] * EMBEDDING_DIM
    for axis, weight in weights.items():
        values[axes[axis]] = weight
    length = math.sqrt(sum(v * v for v in values))
    return [v / length for v in values]


QUERY = vector(x=1)
PRODUCTS = [  # cosine distance to QUERY: SAME 0, NEAR ~0.29, SIDEWAYS 1, OPPOSITE 2
    make_product("OPPOSITE", embedding=vector(x=-1), price="10.00"),
    make_product("SIDEWAYS", embedding=vector(y=1), price="20.00"),
    make_product("NEAR", embedding=vector(x=1, y=1), price="30.00"),
    make_product("SAME", embedding=vector(x=1), price="200.00"),
    make_product("SAME_TWIN", embedding=vector(x=1), price="40.00"),
]


@pytest.fixture(scope="module")
def session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as session:
        session.execute(delete(Product))
        session.add_all(PRODUCTS)
        session.commit()
        yield session
        session.execute(delete(Product))
        session.commit()


def test_closest_first_and_ties_broken_by_id(session: Session) -> None:
    assert vector_search(session, QUERY) == ["SAME", "SAME_TWIN", "NEAR", "SIDEWAYS", "OPPOSITE"]


def test_limit(session: Session) -> None:
    assert vector_search(session, QUERY, limit=2) == ["SAME", "SAME_TWIN"]


def test_filters_remove_products_before_ranking(session: Session) -> None:
    under_100 = build_filters(ParsedQuery(price_max=Decimal("100"), price_max_inclusive=False))
    # SAME ($200) is the closest product but doesn't qualify, so it never appears.
    assert vector_search(session, QUERY, under_100) == ["SAME_TWIN", "NEAR", "SIDEWAYS", "OPPOSITE"]


def test_wrong_dimension_is_rejected(session: Session) -> None:
    with pytest.raises(ValueError, match="expected 384"):
        vector_search(session, [1.0, 0.0, 0.0])
