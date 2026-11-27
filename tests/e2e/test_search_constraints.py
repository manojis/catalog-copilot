"""PRD check on the real catalog with the real models: >= 95% of returned products satisfy every
stated limit, and no trap query creates a filter.

Needs the local stack (docker compose up, alembic upgrade, ingest load). Excluded from the default
run; run with:  uv run pytest -m e2e
"""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from catalog_copilot.db.models import Product
from catalog_copilot.db.session import get_session
from catalog_copilot.evals.constraints import DEFAULT_DATASET, evaluate, format_report, load_dataset
from catalog_copilot.search.service import create_search_service

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]


def test_constraint_satisfaction_on_the_real_catalog() -> None:
    try:
        with get_session() as session:
            products = session.scalar(select(func.count()).select_from(Product)) or 0
    except OperationalError as exc:
        pytest.skip(f"local database not reachable: {exc}")
    if products < 1000:
        pytest.skip(f"catalog not loaded ({products} products); run the ingest first")

    report = evaluate(create_search_service(), load_dataset(ROOT / DEFAULT_DATASET))
    print(format_report(report))
    assert report.false_filters == 0
    assert report.constraint_satisfaction >= report.target
