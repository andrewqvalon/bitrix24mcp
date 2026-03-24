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

    # ---------------------------------------------------------------
    # Auth mode 1 – Incoming webhook (simple, no app registration)
    # ---------------------------------------------------------------
    # e.g. https://your-domain.bitrix24.ru/rest/1/TOKEN/
    bitrix24_webhook_url: str = ""

    # ---------------------------------------------------------------
    # Auth mode 2 – OAuth2 (recommended; user logs in via browser)
    # ---------------------------------------------------------------
    # Bitrix24 application ID (APP.ID) from https://www.bitrix24.ru/apps/
    bitrix24_client_id: str = ""
    # Application secret
    bitrix24_client_secret: str = ""
    # Redirect URI registered for the application.
    # Must match exactly what was set in the Bitrix24 app settings.
    bitrix24_redirect_uri: str = "http://localhost:8765/oauth/callback"

    # ---------------------------------------------------------------
    # Storage
    # ---------------------------------------------------------------
    database_url: str = "sqlite:///bitrix24mcp.sqlite"

    # ---------------------------------------------------------------
    # Sync / cache
    # ---------------------------------------------------------------
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

    def has_oauth_config(self) -> bool:
        """Return True when OAuth client credentials are configured."""
        return bool(self.bitrix24_client_id and self.bitrix24_client_secret)

    def has_webhook_config(self) -> bool:
        """Return True when a webhook URL is configured."""
        return bool(self.bitrix24_webhook_url)


settings = Settings()
