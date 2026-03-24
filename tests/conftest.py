"""Shared pytest fixtures."""
from __future__ import annotations

import os

import pytest

# Use in-memory SQLite for all tests – no PostgreSQL required
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BITRIX24_WEBHOOK_URL", "https://test.bitrix24.ru/rest/1/testtoken")


@pytest.fixture(scope="session")
def in_memory_db():
    """Initialise the SQLite schema once for the whole test session."""
    from bitrix24mcp.db.database import init_db
    init_db()
    yield


@pytest.fixture()
def session(in_memory_db):
    """Provide a transactional session that rolls back after each test."""
    from bitrix24mcp.db.database import get_session
    with get_session() as s:
        yield s
