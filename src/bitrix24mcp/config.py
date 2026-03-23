"""Configuration loaded from environment variables / .env file."""
from __future__ import annotations

from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bitrix24 incoming-webhook base URL
    # e.g. https://your-domain.bitrix24.ru/rest/1/TOKEN/
    bitrix24_webhook_url: str = ""

    # PostgreSQL DSN
    database_url: str = "sqlite:///bitrix24mcp.sqlite"

    # Background full-sync period (seconds)
    sync_interval: int = 3600

    # Max age of cached records before the MCP layer forces a refresh (seconds)
    cache_ttl: int = 300

    # Entity types to include in sync
    sync_entities: str = "contacts,companies,deals,leads,pipelines,activities"

    @field_validator("bitrix24_webhook_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    def entity_list(self) -> List[str]:
        return [e.strip() for e in self.sync_entities.split(",") if e.strip()]


settings = Settings()
