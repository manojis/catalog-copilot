"""Shared fixtures. Integration tests run against a throwaway Postgres container."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine

PGVECTOR_IMAGE = "pgvector/pgvector:0.8.0-pg17"  # keep in sync with docker-compose.yml
ROOT = Path(__file__).resolve().parents[1]

# testcontainers' cleanup container mounts the Docker socket by its path *inside* the Docker
# host. That is /var/run/docker.sock on Docker Desktop, Rancher Desktop and Linux, even when the
# client connects through another path (e.g. ~/.rd/docker.sock). An explicit env var still wins.
os.environ.setdefault("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", "/var/run/docker.sock")


def alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """Start a fresh Postgres + pgvector container for the test session."""
    import docker
    from testcontainers.community.postgres import PostgresContainer

    try:
        docker.from_env().ping()
    except Exception as exc:
        pytest.skip(f"Docker is not running, skipping integration tests: {exc}")

    # Any other failure (bad image, socket config) should fail loudly, not skip.
    container = PostgresContainer(PGVECTOR_IMAGE, driver="psycopg").start()
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture(scope="session")
def migrated_engine(database_url: str) -> Iterator[Engine]:
    """Engine for a database migrated to the latest schema."""
    command.upgrade(alembic_config(database_url), "head")
    engine = create_engine(database_url)
    yield engine
    engine.dispose()
