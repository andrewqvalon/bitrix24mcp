"""Unit tests for the MCP tool dispatch layer and the DB repository."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# Make sure env vars are set before importing app modules (conftest.py does this)


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------

class TestRepository:
    def test_upsert_and_find_contact(self, session):
        from bitrix24mcp.db.repository import search_contacts, upsert_contact

        data = {
            "ID": "42",
            "NAME": "Ivan",
            "LAST_NAME": "Petrov",
            "SECOND_NAME": "",
            "PHONE": [{"VALUE": "+79001234567", "VALUE_TYPE": "WORK"}],
            "EMAIL": [{"VALUE": "ivan@example.com", "VALUE_TYPE": "WORK"}],
            "COMPANY_ID": "10",
            "ASSIGNED_BY_ID": "1",
            "SOURCE_ID": "WEB",
            "COMMENTS": "VIP client",
            "DATE_CREATE": "2024-01-15T10:00:00",
            "DATE_MODIFY": "2024-06-01T12:00:00",
        }
        upsert_contact(session, data)
        session.flush()

        results = search_contacts(session, query="Ivan")
        assert len(results) == 1
        assert results[0].id == 42
        assert results[0].last_name == "Petrov"

    def test_search_contact_by_phone(self, session):
        from bitrix24mcp.db.repository import search_contacts, upsert_contact

        upsert_contact(
            session,
            {
                "ID": "43",
                "NAME": "Olga",
                "LAST_NAME": "Ivanova",
                "PHONE": [{"VALUE": "+79009876543", "VALUE_TYPE": "WORK"}],
                "EMAIL": [],
                "DATE_CREATE": None,
                "DATE_MODIFY": None,
            },
        )
        session.flush()
        results = search_contacts(session, query="9876543")
        assert any(r.id == 43 for r in results)

    def test_upsert_and_find_company(self, session):
        from bitrix24mcp.db.repository import search_companies, upsert_company

        upsert_company(
            session,
            {
                "ID": "5",
                "TITLE": "Acme Corp",
                "PHONE": [{"VALUE": "+74951234567", "VALUE_TYPE": "WORK"}],
                "EMAIL": [],
                "ASSIGNED_BY_ID": "1",
                "INDUSTRY": "IT",
                "EMPLOYEES": "50-100",
                "REVENUE": "5000000",
                "DATE_CREATE": "2023-01-01T00:00:00",
                "DATE_MODIFY": None,
            },
        )
        session.flush()
        results = search_companies(session, query="Acme")
        assert len(results) >= 1
        assert results[0].industry == "IT"

    def test_upsert_and_search_deal(self, session):
        from bitrix24mcp.db.repository import search_deals, upsert_deal

        upsert_deal(
            session,
            {
                "ID": "100",
                "TITLE": "Big Contract",
                "STAGE_ID": "NEW",
                "CATEGORY_ID": "0",
                "CONTACT_ID": "42",
                "COMPANY_ID": "5",
                "ASSIGNED_BY_ID": "1",
                "OPPORTUNITY": "250000",
                "CURRENCY_ID": "RUB",
                "IS_WON": "N",
                "CLOSED": "N",
                "DATE_CREATE": "2024-03-01T09:00:00",
                "DATE_MODIFY": None,
                "CLOSEDATE": None,
            },
        )
        session.flush()

        results = search_deals(session, query="Big")
        assert any(r.id == 100 for r in results)

        open_deals = search_deals(session, is_closed=False)
        assert any(r.id == 100 for r in open_deals)

    def test_upsert_and_search_lead(self, session):
        from bitrix24mcp.db.repository import search_leads, upsert_lead

        upsert_lead(
            session,
            {
                "ID": "200",
                "TITLE": "Hot Lead",
                "NAME": "Sergey",
                "LAST_NAME": "Sidorov",
                "PHONE": [{"VALUE": "+79001111111", "VALUE_TYPE": "MOBILE"}],
                "EMAIL": [{"VALUE": "sergey@mail.ru", "VALUE_TYPE": "HOME"}],
                "STATUS_ID": "NEW",
                "ASSIGNED_BY_ID": "1",
                "OPPORTUNITY": "50000",
                "CURRENCY_ID": "RUB",
                "DATE_CREATE": "2025-01-01T00:00:00",
                "DATE_MODIFY": None,
            },
        )
        session.flush()
        results = search_leads(session, query="Sergey")
        assert any(r.id == 200 for r in results)

    def test_upsert_pipeline_and_stage(self, session):
        from bitrix24mcp.db.repository import upsert_pipeline, upsert_stage
        from bitrix24mcp.db.models import Pipeline, Stage

        upsert_pipeline(session, {"ID": 0, "NAME": "Default", "IS_DEFAULT": "Y"})
        upsert_stage(
            session,
            0,
            {"STATUS_ID": "NEW", "NAME": "New", "SORT": 10, "TYPE": "WORK"},
        )
        session.flush()

        pipeline = session.get(Pipeline, 0)
        assert pipeline is not None
        assert pipeline.is_default is True

        stage = session.query(Stage).filter(Stage.status_id == "NEW").first()
        assert stage is not None
        assert stage.name == "New"

    def test_sync_state(self, session):
        from bitrix24mcp.db.repository import get_sync_state, set_sync_state

        set_sync_state(session, "contacts", last_id=500)
        session.flush()

        state = get_sync_state(session, "contacts")
        assert state is not None
        assert state.last_id == 500
        assert state.last_sync_at is not None


# ---------------------------------------------------------------------------
# MCP server tool dispatch
# ---------------------------------------------------------------------------

class TestMCPTools:
    """Test the synchronous _dispatch() function."""

    def test_find_contacts_empty(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        result = _dispatch("find_contacts", {"query": "NoSuchPerson_xyz"})
        assert isinstance(result, list)

    def test_find_deals_empty(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        result = _dispatch("find_deals", {})
        assert isinstance(result, list)

    def test_list_pipelines_empty_hint(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        result = _dispatch("list_pipelines", {})
        # Either empty list or hint message
        assert isinstance(result, list)

    def test_get_portfolio_report_structure(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        result = _dispatch("get_portfolio_report", {})
        assert "summary" in result
        assert "stage_breakdown" in result
        assert "pipeline_breakdown" in result

    def test_get_contact_not_found(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        result = _dispatch("get_contact", {"id": 999999})
        assert "error" in result

    def test_get_deal_not_found(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        result = _dispatch("get_deal", {"id": 999999})
        assert "error" in result

    def test_get_lead_not_found(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        result = _dispatch("get_lead", {"id": 999999})
        assert "error" in result

    def test_get_company_not_found(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        result = _dispatch("get_company", {"id": 999999})
        assert "error" in result

    def test_unknown_tool_raises(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        with pytest.raises(ValueError, match="Unknown tool"):
            _dispatch("nonexistent_tool", {})

    def test_get_client_summary_no_args(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        result = _dispatch("get_client_summary", {})
        assert "error" in result

    def test_sync_crm_data_no_webhook_raises(self, in_memory_db):
        """When webhook URL is empty, sync should raise RuntimeError."""
        import os
        original = os.environ.get("BITRIX24_WEBHOOK_URL", "")
        os.environ["BITRIX24_WEBHOOK_URL"] = ""

        try:
            from bitrix24mcp import config
            # Force settings reload
            config.settings.bitrix24_webhook_url = ""
            from bitrix24mcp.server import _dispatch
            with pytest.raises(RuntimeError, match="BITRIX24_WEBHOOK_URL"):
                _dispatch("sync_crm_data", {})
        finally:
            os.environ["BITRIX24_WEBHOOK_URL"] = original
            config.settings.bitrix24_webhook_url = original.rstrip("/")

    def test_find_contacts_returns_seeded_data(self, in_memory_db):
        """Insert data via repo and confirm find_contacts retrieves it."""
        from bitrix24mcp.db.database import get_session
        from bitrix24mcp.db.repository import upsert_contact
        from bitrix24mcp.server import _dispatch

        with get_session() as session:
            upsert_contact(
                session,
                {
                    "ID": "9001",
                    "NAME": "Unique_MCPTest_Name",
                    "LAST_NAME": "Smith",
                    "PHONE": [],
                    "EMAIL": [],
                    "DATE_CREATE": None,
                    "DATE_MODIFY": None,
                },
            )

        result = _dispatch("find_contacts", {"query": "Unique_MCPTest_Name"})
        assert isinstance(result, list)
        assert any(r["id"] == 9001 for r in result)
