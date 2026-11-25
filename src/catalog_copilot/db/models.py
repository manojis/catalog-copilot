"""SQLAlchemy models. Schema changes go through Alembic migrations in migrations/versions/."""

from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Index, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384  # BAAI/bge-small-en-v1.5

# Keyword search terms, built by Postgres. Title words weigh most (A), then brand (B), then rest.
SEARCH_TSV_EXPR = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(brand, '')), 'B') || "
    "setweight(to_tsvector('english', search_text), 'C')"
)


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # Amazon ASIN
    title: Mapped[str] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text)
    category_path: Mapped[str | None] = mapped_column(Text)  # "Clothing > Shoes > Men > Athletic"
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # gender, color, size, material ...
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    # The product text that is embedded (BGE) and read by the reranker (MiniLM).
    search_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    search_tsv: Mapped[str] = mapped_column(TSVECTOR, Computed(SEARCH_TSV_EXPR, persisted=True))

    # No vector index: at ~30K rows an exact scan takes milliseconds and never under-fills
    # filtered results. Add HNSW only if the catalog grows into the millions.
    __table_args__ = (
        Index("products_search_tsv_idx", "search_tsv", postgresql_using="gin"),
        Index("products_price_idx", "price"),
        Index("products_brand_idx", func.lower(brand)),
        Index(
            "products_attributes_idx",
            "attributes",
            postgresql_using="gin",
            postgresql_ops={"attributes": "jsonb_path_ops"},
        ),
    )
