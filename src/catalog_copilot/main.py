"""FastAPI application entry point."""

import uvicorn
from fastapi import FastAPI

from catalog_copilot import __version__
from catalog_copilot.config import get_settings

app = FastAPI(title="catalog-copilot", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__, "env": get_settings().env}


def run() -> None:
    settings = get_settings()
    uvicorn.run("catalog_copilot.main:app", host=settings.host, port=settings.port, reload=True)
