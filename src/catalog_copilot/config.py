"""Application settings, loaded from environment variables or a local .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    # Cross-encoder that rescores the merged candidates (reads query + product text together).
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    # How many RRF candidates the reranker scores. Cost grows linearly: ~240 ms for 30 on an
    # 18-core laptop (~800 ms for all ~85). Lower it on small servers.
    rerank_candidates: int = Field(default=30, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
