"""SQLAlchemy ORM models for the local CRM cache."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Contact(Base):
    """Cached Bitrix24 CRM contact."""

    __tablename__ = "crm_contacts"

    id = Column(Integer, primary_key=True)  # Bitrix24 ID
    name = Column(String(512), nullable=False, index=True)
    first_name = Column(String(256))
    last_name = Column(String(256))
    second_name = Column(String(256))
    phone = Column(String(512))    # JSON-encoded list
    email = Column(String(512))    # JSON-encoded list
    company_id = Column(Integer, index=True)
    assigned_by_id = Column(Integer)
    source_id = Column(String(128))
    comments = Column(Text)
    date_create = Column(DateTime)
    date_modify = Column(DateTime)
    # Full raw JSON from Bitrix24 (for any extra fields)
    raw_json = Column(Text)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Company(Base):
    """Cached Bitrix24 CRM company."""

    __tablename__ = "crm_companies"

    id = Column(Integer, primary_key=True)
    title = Column(String(512), nullable=False, index=True)
    phone = Column(String(512))
    email = Column(String(512))
    assigned_by_id = Column(Integer)
    industry = Column(String(256))
    employees = Column(String(64))
    revenue = Column(Float)
    comments = Column(Text)
    date_create = Column(DateTime)
    date_modify = Column(DateTime)
    raw_json = Column(Text)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Pipeline(Base):
    """Deal category / funnel."""

    __tablename__ = "crm_pipelines"

    id = Column(Integer, primary_key=True)  # 0 = default
    name = Column(String(512), nullable=False)
    is_default = Column(Boolean, default=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Stage(Base):
    """Deal stage belonging to a pipeline."""

    __tablename__ = "crm_stages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status_id = Column(String(128), nullable=False, unique=True)
    pipeline_id = Column(Integer, index=True)
    name = Column(String(512), nullable=False)
    sort = Column(Integer, default=0)
    is_final = Column(Boolean, default=False)
    is_won = Column(Boolean, default=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Deal(Base):
    """Cached Bitrix24 CRM deal."""

    __tablename__ = "crm_deals"

    id = Column(Integer, primary_key=True)
    title = Column(String(512), nullable=False, index=True)
    stage_id = Column(String(128), index=True)
    pipeline_id = Column(Integer, index=True, default=0)
    contact_id = Column(Integer, index=True)
    company_id = Column(Integer, index=True)
    assigned_by_id = Column(Integer)
    opportunity = Column(Float)
    currency_id = Column(String(16))
    is_won = Column(Boolean, default=False)
    is_failed = Column(Boolean, default=False)
    is_closed = Column(Boolean, default=False)
    comments = Column(Text)
    source_id = Column(String(128))
    date_create = Column(DateTime)
    date_modify = Column(DateTime)
    close_date = Column(DateTime)
    raw_json = Column(Text)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Lead(Base):
    """Cached Bitrix24 CRM lead."""

    __tablename__ = "crm_leads"

    id = Column(Integer, primary_key=True)
    title = Column(String(512), nullable=False, index=True)
    name = Column(String(512), index=True)
    first_name = Column(String(256))
    last_name = Column(String(256))
    phone = Column(String(512))
    email = Column(String(512))
    status_id = Column(String(128), index=True)
    assigned_by_id = Column(Integer)
    opportunity = Column(Float)
    currency_id = Column(String(16))
    company_id = Column(Integer, index=True)
    contact_id = Column(Integer)
    source_id = Column(String(128))
    comments = Column(Text)
    date_create = Column(DateTime)
    date_modify = Column(DateTime)
    raw_json = Column(Text)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Activity(Base):
    """CRM activity / timeline event (call, email, meeting, note …)."""

    __tablename__ = "crm_activities"

    id = Column(Integer, primary_key=True)
    type_id = Column(Integer, index=True)     # 1=call, 2=email, 3=meeting, …
    type_name = Column(String(64))
    owner_type_id = Column(Integer, index=True)  # 1=lead,2=deal,3=contact,4=company
    owner_id = Column(Integer, index=True)
    subject = Column(String(512))
    description = Column(Text)
    responsible_id = Column(Integer)
    completed = Column(Boolean, default=False)
    deadline = Column(DateTime)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    raw_json = Column(Text)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SyncState(Base):
    """Tracks the last successful synchronisation time per entity type."""

    __tablename__ = "sync_state"

    entity_type = Column(String(64), primary_key=True)
    last_sync_at = Column(DateTime)
    last_id = Column(BigInteger, default=0)


class OAuthToken(Base):
    """Stores the Bitrix24 OAuth2 tokens obtained via the authorization flow.

    Only one active token row is expected (keyed by ``client_id``).
    """

    __tablename__ = "oauth_tokens"

    client_id = Column(String(256), primary_key=True)
    domain = Column(String(256), nullable=False)   # e.g. mycompany.bitrix24.ru
    member_id = Column(String(256))                 # portal unique identifier
    access_token = Column(String(1024), nullable=False)
    refresh_token = Column(String(1024), nullable=False)
    expires_at = Column(DateTime, nullable=False)   # UTC datetime when access_token expires
    scope = Column(String(1024))                    # granted OAuth scopes
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
