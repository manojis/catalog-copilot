"""Engine and session factory."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from catalog_copilot.config import get_settings


def sqlalchemy_url(database_url: str) -> str:
    """Use the psycopg 3 driver for plain postgresql:// URLs."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


@lru_cache
def get_engine() -> Engine:
    return create_engine(sqlalchemy_url(get_settings().database_url), pool_pre_ping=True)


def get_session() -> Session:
    return sessionmaker(bind=get_engine())()
