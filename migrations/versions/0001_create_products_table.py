"""create products table

Revision ID: 0001
Revises:
Create Date: 2026-11-21 15:52:53.874664
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_TSV_EXPR = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(brand, '')), 'B') || "
    "setweight(to_tsvector('english', search_text), 'C')"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "products",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("category_path", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_TSV_EXPR, persisted=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("products_search_tsv_idx", "products", ["search_tsv"], postgresql_using="gin")
    op.create_index("products_price_idx", "products", ["price"])
    op.create_index("products_brand_idx", "products", [sa.literal_column("lower(brand)")])
    op.create_index(
        "products_attributes_idx",
        "products",
        ["attributes"],
        postgresql_using="gin",
        postgresql_ops={"attributes": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("products_attributes_idx", table_name="products")
    op.drop_index("products_brand_idx", table_name="products")
    op.drop_index("products_price_idx", table_name="products")
    op.drop_index("products_search_tsv_idx", table_name="products")
    op.drop_table("products")
    # The vector extension is left installed: other databases objects may depend on it.
