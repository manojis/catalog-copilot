"""Application settings, loaded from environment variables or a local .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CC_", extra="ignore")

    env: str = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = "postgresql://catalog:catalog@localhost:5432/catalog"
    # Ingest and search must use the same embedding model, or vectors are not comparable.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    model_cache_dir: str = str(Path.home() / ".cache" / "fastembed")


@lru_cache
def get_settings() -> Settings:
    return Settings()
