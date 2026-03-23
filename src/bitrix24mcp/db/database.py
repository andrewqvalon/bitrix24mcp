"""Database engine and session factory."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from bitrix24mcp.config import settings
from bitrix24mcp.db.models import Base

_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={} if not settings.database_url.startswith("sqlite") else {"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def init_db() -> None:
    """Create all tables (no-op if they already exist)."""
    Base.metadata.create_all(bind=_engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
