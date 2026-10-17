"""Application settings, loaded from environment variables or a local .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CC_", extra="ignore")

    env: str = "dev"
    host: str = "127.0.0.1"
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()
