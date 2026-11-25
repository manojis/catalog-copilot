"""Migrations create the schema the models expect, and can be rolled back."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from catalog_copilot.db.models import EMBEDDING_DIM, Base, Product
from tests.conftest import alembic_config

pytestmark = pytest.mark.integration


def test_models_match_migrations(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_products_table_and_indexes_exist(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    indexes = {ix["name"] for ix in inspector.get_indexes("products")}
    assert indexes == {
        "products_search_tsv_idx",
        "products_price_idx",
        "products_brand_idx",
        "products_attributes_idx",
    }


def test_product_round_trip_keyword_and_vector_search(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        session.add(
            Product(
                id="B0TEST0001",
                title="New Balance 880 Wide (2E) Running Shoe",
                brand="New Balance",
                price=89,
                attributes={"gender": "men"},
                search_text="New Balance 880 Wide (2E) Running Shoe. Breathable mesh upper.",
                embedding=[1.0] + [0.0] * (EMBEDDING_DIM - 1),
            )
        )
        session.flush()

        # search_tsv is filled in by Postgres, with words reduced to their roots
        tsv = session.scalar(select(Product.search_tsv).where(Product.id == "B0TEST0001"))
        assert tsv is not None
        assert "'run'" in tsv and "'2e'" in tsv

        keyword_hit = session.scalar(
            select(Product.id).where(
                Product.search_tsv.op("@@")(text("websearch_to_tsquery('english', 'running')"))
            )
        )
        assert keyword_hit == "B0TEST0001"

        query_vector = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
        distance = session.scalar(select(Product.embedding.cosine_distance(query_vector)))
        assert distance == pytest.approx(0.0)

        session.rollback()


def test_downgrade_then_upgrade(database_url: str, migrated_engine: Engine) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "base")
    assert not inspect(migrated_engine).has_table("products")
    command.upgrade(config, "head")
    assert inspect(migrated_engine).has_table("products")
