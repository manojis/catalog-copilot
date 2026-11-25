"""Command line entry point: catalog-copilot-ingest {download,load}."""

import argparse
import logging
import time
from pathlib import Path

from catalog_copilot.db.session import get_session
from catalog_copilot.embeddings import get_embedder
from catalog_copilot.ingest.pipeline import IngestStats, download_snapshot, load_products
from catalog_copilot.ingest.source import DATASET_URL

logger = logging.getLogger("catalog_copilot.ingest")

DEFAULT_LIMIT = 30_000


def default_snapshot(limit: int) -> Path:
    return Path("data/raw") / f"clothing_{limit}.jsonl.gz"


def report(stage: str, stats: IngestStats, started: float) -> None:
    skipped = ", ".join(f"{reason}: {n}" for reason, n in stats.skipped.most_common()) or "none"
    logger.info(
        "%s done in %.1fs: read %d, kept %d, skipped (%s)",
        stage,
        time.perf_counter() - started,
        stats.read,
        stats.kept,
        skipped,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="catalog-copilot-ingest", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    download = commands.add_parser("download", help="save a raw snapshot of N usable products")
    download.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    download.add_argument("--source", default=DATASET_URL, help="dataset URL or local file")
    download.add_argument("--output", type=Path, help="default: data/raw/clothing_<limit>.jsonl.gz")

    load = commands.add_parser("load", help="clean, embed and upsert a snapshot into Postgres")
    load.add_argument("--input", type=Path, help="default: data/raw/clothing_<limit>.jsonl.gz")
    load.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="picks the default input")
    load.add_argument("--batch-size", type=int, default=256)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per HTTP request is noise
    started = time.perf_counter()

    if args.command == "download":
        output = args.output or default_snapshot(args.limit)
        logger.info("Downloading %d usable products from %s to %s", args.limit, args.source, output)
        report("download", download_snapshot(args.source, output, args.limit), started)
    else:
        source = args.input or default_snapshot(args.limit)
        logger.info("Loading %s (embedding model loads first, ~10s)", source)
        stats = load_products(str(source), get_embedder(), get_session, args.batch_size)
        report("load", stats, started)


if __name__ == "__main__":
    main()
