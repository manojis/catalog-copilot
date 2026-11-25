"""Read raw product records from the Amazon Reviews 2023 dataset (URL) or a local snapshot."""

import gzip
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Amazon Reviews 2023 (McAuley Lab), Clothing/Shoes/Jewelry product metadata. ~18 GB, so it is
# streamed and we stop reading once we have enough products.
DATASET_URL = (
    "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/"
    "raw/meta_categories/meta_Clothing_Shoes_and_Jewelry.jsonl"
)


def iter_lines(source: str) -> Iterator[str]:
    """Yield lines from an http(s) URL (streamed) or a local .jsonl / .jsonl.gz file."""
    if source.startswith(("http://", "https://")):
        timeout = httpx.Timeout(30.0, read=120.0)
        with httpx.stream("GET", source, follow_redirects=True, timeout=timeout) as response:
            response.raise_for_status()
            yield from response.iter_lines()
    else:
        path = Path(source)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as file:
            yield from file


def iter_records(source: str) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON records, skipping blank or malformed lines."""
    for line_number, line in enumerate(iter_lines(source), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed JSON on line %d", line_number)
