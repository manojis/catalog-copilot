"""Ingest stages: download (extract a raw snapshot) and load (clean, embed, upsert)."""

import gzip
import json
import logging
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from itertools import batched
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from catalog_copilot.db.models import EMBEDDING_DIM, Product
from catalog_copilot.embeddings import Embedder
from catalog_copilot.ingest.clean import ProductRecord, SkipRecord, clean_record
from catalog_copilot.ingest.source import iter_records

logger = logging.getLogger(__name__)

# Columns refreshed when a product is loaded again (search_tsv is computed by Postgres).
UPSERT_COLUMNS = (
    "title", "brand", "category_path", "price", "attributes",
    "description", "url", "search_text", "embedding",
)  # fmt: skip


@dataclass
class IngestStats:
    read: int = 0
    kept: int = 0
    skipped: Counter[str] = field(default_factory=Counter)


def iter_clean(records: Iterable[dict[str, Any]], stats: IngestStats) -> Iterator[ProductRecord]:
    """Clean records, counting why rejected ones were skipped. Duplicate ids are skipped too."""
    seen: set[str] = set()
    for raw in records:
        stats.read += 1
        try:
            product = clean_record(raw)
        except SkipRecord as reason:
            stats.skipped[str(reason)] += 1
            continue
        if product.id in seen:
            stats.skipped["duplicate id"] += 1
            continue
        seen.add(product.id)
        stats.kept += 1
        yield product


def download_snapshot(source: str, output: Path, limit: int) -> IngestStats:
    """Stream the raw dataset and save the first `limit` usable records, unchanged, as .jsonl.gz.

    Keeping the raw snapshot makes loads reproducible and lets us re-run cleaning
    without downloading again.
    """
    stats = IngestStats()
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".partial")
    with gzip.open(tmp, "wt", encoding="utf-8") as out:
        for raw in iter_records(source):
            stats.read += 1
            try:
                clean_record(raw)
            except SkipRecord as reason:
                stats.skipped[str(reason)] += 1
                continue
            out.write(json.dumps(raw) + "\n")
            stats.kept += 1
            if stats.kept % 5000 == 0:
                logger.info("download: kept %d of %d read", stats.kept, stats.read)
            if stats.kept >= limit:
                break
    tmp.rename(output)  # only a complete file gets the final name
    return stats


def upsert_products(
    session: Session, products: list[ProductRecord], vectors: list[list[float]]
) -> None:
    """Insert products, or update them if the id already exists (idempotent re-runs)."""
    rows = [{**p.model_dump(), "embedding": v} for p, v in zip(products, vectors, strict=True)]
    stmt = insert(Product).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Product.id],
        set_={column: stmt.excluded[column] for column in UPSERT_COLUMNS},
    )
    session.execute(stmt)


def load_products(
    source: str,
    embedder: Embedder,
    session_factory: Callable[[], Session],
    batch_size: int = 256,
) -> IngestStats:
    """Clean, embed and upsert products in batches. Safe to re-run: existing ids are updated."""
    stats = IngestStats()
    started = time.perf_counter()
    for batch in batched(iter_clean(iter_records(source), stats), batch_size):
        products = list(batch)
        vectors = embedder.embed_documents([p.search_text for p in products])
        if len(vectors[0]) != EMBEDDING_DIM:
            raise ValueError(
                f"Embedding model returned {len(vectors[0])} dims; column is {EMBEDDING_DIM}"
            )
        with session_factory() as session, session.begin():
            upsert_products(session, products, vectors)
        elapsed = time.perf_counter() - started
        logger.info(
            "load: %d products (%.0f/s), skipped %d",
            stats.kept,
            stats.kept / elapsed,
            sum(stats.skipped.values()),
        )
    return stats
