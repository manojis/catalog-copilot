"""Download + load end to end against a real Postgres, with a fake embedder (no model download)."""

import gzip
import json
from collections.abc import Iterator, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from catalog_copilot.db.models import EMBEDDING_DIM, Product
from catalog_copilot.ingest.pipeline import download_snapshot, load_products

pytestmark = pytest.mark.integration


class FakeEmbedder:
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(t))] + [0.0] * (EMBEDDING_DIM - 1) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def raw(asin: str, title: str, price: Any) -> dict[str, Any]:
    return {
        "parent_asin": asin,
        "title": title,
        "price": price,
        "store": "Brooks",
        "categories": ["Clothing, Shoes & Jewelry", "Women", "Shoes"],
        "details": {"Department": "womens"},
        "features": ["Engineered mesh"],
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


@pytest.fixture
def session_factory(migrated_engine: Engine) -> Iterator[sessionmaker[Session]]:
    factory = sessionmaker(bind=migrated_engine)
    yield factory
    with factory() as session, session.begin():
        session.execute(delete(Product))


def test_download_keeps_only_usable_records(tmp_path: Path) -> None:
    source = tmp_path / "raw.jsonl"
    write_jsonl(
        source,
        [raw("B1", "Ghost 15", 99), raw("B2", "No price", None), raw("B3", "Glycerin", 120)],
    )
    output = tmp_path / "snapshot.jsonl.gz"

    stats = download_snapshot(str(source), output, limit=2)

    assert (stats.kept, dict(stats.skipped)) == (2, {"missing or invalid price": 1})
    with gzip.open(output, "rt") as f:
        assert [json.loads(line)["parent_asin"] for line in f] == ["B1", "B3"]


def test_load_inserts_then_updates_idempotently(
    tmp_path: Path, session_factory: sessionmaker[Session]
) -> None:
    source = tmp_path / "snapshot.jsonl"
    write_jsonl(
        source, [raw("B1", "Ghost 15", 99), raw("B1", "Dup", 1), raw("B2", "Adrenaline", 140)]
    )

    stats = load_products(str(source), FakeEmbedder(), session_factory, batch_size=1)
    assert (stats.kept, dict(stats.skipped)) == (2, {"duplicate id": 1})

    # Re-running with a changed price updates the row instead of duplicating it.
    write_jsonl(source, [raw("B1", "Ghost 15", 89.5)])
    load_products(str(source), FakeEmbedder(), session_factory)

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Product)) == 2
        product = session.get_one(Product, "B1")
        assert product.price == Decimal("89.50")
        assert product.attributes == {"gender": "women"}
        assert product.search_text.startswith("Ghost 15. Brand: Brooks. Category: Women > Shoes")
        assert len(product.embedding) == EMBEDDING_DIM
        assert "'ghost'" in product.search_tsv
