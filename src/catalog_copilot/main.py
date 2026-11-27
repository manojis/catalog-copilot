"""FastAPI application entry point."""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from catalog_copilot import __version__
from catalog_copilot.config import get_settings
from catalog_copilot.db.session import get_engine
from catalog_copilot.search.query_parser import MAX_QUERY_CHARS
from catalog_copilot.search.service import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    SearchResponse,
    SearchService,
    create_search_service,
)

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Send the app's own log lines (per-search timings, startup) to stderr.

    Uvicorn configures only its own loggers; without this, catalog_copilot's INFO lines are
    silently dropped.
    """
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the models and the catalog's brand list once, before the first request.

    If the database is unreachable the app refuses to start (fail fast): a search service
    without its brand list would silently parse queries worse. The platform restarts it.
    """
    configure_logging()
    started = time.perf_counter()
    try:
        app.state.search_service = create_search_service()
    except OperationalError:
        url = get_engine().url.render_as_string(hide_password=True)
        logger.error("Cannot start: database unreachable at %s", url)
        raise
    logger.info("Search service ready in %.1f s", time.perf_counter() - started)
    yield


app = FastAPI(title="catalog-copilot", version=__version__, lifespan=lifespan)


def get_search_service(request: Request) -> SearchService:
    service: SearchService = request.app.state.search_service
    return service


@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    # Log the cause for us; tell the caller only what they can act on.
    logger.error("Database error during %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(
        status_code=503,
        content={"detail": "Search is temporarily unavailable. Please try again shortly."},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__, "env": get_settings().env}


# A plain `def`, not `async def`: search blocks on the database and on model inference, so
# FastAPI runs it in a worker thread instead of freezing the event loop for every request.
@app.get("/search", response_model=SearchResponse)
def search(
    q: Annotated[
        str,
        Query(
            min_length=1,
            max_length=MAX_QUERY_CHARS,
            description='What the shopper typed, e.g. "women\'s black running shoes under $100".',
        ),
    ],
    service: Annotated[SearchService, Depends(get_search_service)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Number of results.")] = (
        DEFAULT_LIMIT
    ),
) -> SearchResponse:
    """Hybrid product search: hard limits become filters, the rest is ranked by meaning."""
    return service.search(q, limit)


def run() -> None:
    settings = get_settings()
    uvicorn.run("catalog_copilot.main:app", host=settings.host, port=settings.port, reload=True)
