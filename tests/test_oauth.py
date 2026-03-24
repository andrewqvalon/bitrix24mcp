"""Unit tests for the Bitrix24 OAuth2 flow."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# Ensure env vars are set before importing (conftest.py)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BITRIX24_WEBHOOK_URL", "https://test.bitrix24.ru/rest/1/testtoken")


# ---------------------------------------------------------------------------
# Bitrix24OAuthManager unit tests
# ---------------------------------------------------------------------------

class TestOAuthManager:
    def _make_manager(self):
        from bitrix24mcp.bitrix.oauth import Bitrix24OAuthManager
        return Bitrix24OAuthManager(
            client_id="local.testapp",
            client_secret="testsecret",
            redirect_uri="http://localhost:8765/oauth/callback",
        )

    def test_get_authorization_url_no_domain(self):
        mgr = self._make_manager()
        url = mgr.get_authorization_url()
        assert "oauth.bitrix.info" in url
        assert "client_id=local.testapp" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url

    def test_get_authorization_url_with_domain(self):
        mgr = self._make_manager()
        url = mgr.get_authorization_url(domain="mycompany.bitrix24.ru")
        assert "mycompany.bitrix24.ru/oauth/authorize" in url
        assert "client_id=local.testapp" in url

    def test_exchange_code_success(self):
        mgr = self._make_manager()
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {
            "access_token": "acc123",
            "refresh_token": "ref456",
            "expires_in": 3600,
            "domain": "mycompany.bitrix24.ru",
            "member_id": "abc",
        }
        with patch.object(mgr._http, "post", return_value=fake_resp):
            data = mgr.exchange_code("authcode")
        assert data["access_token"] == "acc123"
        assert data["refresh_token"] == "ref456"

    def test_exchange_code_error_raises(self):
        from bitrix24mcp.bitrix.oauth import OAuthError
        mgr = self._make_manager()
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {
            "error": "invalid_client",
            "error_description": "Wrong credentials",
        }
        with patch.object(mgr._http, "post", return_value=fake_resp):
            with pytest.raises(OAuthError, match="invalid_client"):
                mgr.exchange_code("badcode")

    def test_refresh_token_success(self):
        mgr = self._make_manager()
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {
            "access_token": "newacc",
            "refresh_token": "newref",
            "expires_in": 3600,
            "domain": "mycompany.bitrix24.ru",
        }
        with patch.object(mgr._http, "post", return_value=fake_resp):
            data = mgr.refresh_token("oldrefresh")
        assert data["access_token"] == "newacc"


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------

class TestTokenPersistence:
    def test_save_and_load_token(self, session):
        from bitrix24mcp.bitrix.oauth import load_token, save_token

        token_data = {
            "access_token": "acc_abc",
            "refresh_token": "ref_xyz",
            "expires_in": 3600,
            "domain": "example.bitrix24.ru",
            "member_id": "mid123",
            "scope": "crm",
        }
        save_token(session, "local.myapp", token_data)
        session.flush()

        loaded = load_token(session, "local.myapp")
        assert loaded is not None
        assert loaded.access_token == "acc_abc"
        assert loaded.domain == "example.bitrix24.ru"
        assert loaded.member_id == "mid123"

    def test_save_token_updates_existing(self, session):
        from bitrix24mcp.bitrix.oauth import load_token, save_token

        save_token(session, "local.myapp2", {
            "access_token": "old",
            "refresh_token": "oldref",
            "expires_in": 3600,
            "domain": "a.bitrix24.ru",
        })
        session.flush()

        save_token(session, "local.myapp2", {
            "access_token": "new",
            "refresh_token": "newref",
            "expires_in": 3600,
            "domain": "a.bitrix24.ru",
        })
        session.flush()

        loaded = load_token(session, "local.myapp2")
        assert loaded is not None
        assert loaded.access_token == "new"

    def test_get_valid_access_token_fresh(self, session):
        """A fresh token (not yet expired) should be returned as-is."""
        from bitrix24mcp.bitrix.oauth import get_valid_access_token, save_token

        save_token(session, "local.freshapp", {
            "access_token": "freshtoken",
            "refresh_token": "freshref",
            "expires_in": 3600,
            "domain": "x.bitrix24.ru",
        })
        session.flush()

        token = get_valid_access_token(session, "local.freshapp", "secret")
        assert token == "freshtoken"

    def test_get_valid_access_token_expired_triggers_refresh(self, session):
        """An expired token should trigger a refresh call."""
        from bitrix24mcp.bitrix.oauth import get_valid_access_token, save_token
        from bitrix24mcp.db.models import OAuthToken

        # Manually insert an already-expired token
        obj = OAuthToken(
            client_id="local.expiredapp",
            domain="y.bitrix24.ru",
            access_token="expiredtoken",
            refresh_token="goodrefresh",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            scope="crm",
        )
        session.add(obj)
        session.flush()

        new_token_data = {
            "access_token": "freshtoken2",
            "refresh_token": "freshref2",
            "expires_in": 3600,
            "domain": "y.bitrix24.ru",
        }

        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = new_token_data

        from bitrix24mcp.bitrix.oauth import Bitrix24OAuthManager
        with patch.object(Bitrix24OAuthManager, "refresh_token", return_value=new_token_data):
            token = get_valid_access_token(session, "local.expiredapp", "secret")

        assert token == "freshtoken2"

    def test_get_valid_access_token_missing_returns_none(self, session):
        from bitrix24mcp.bitrix.oauth import get_valid_access_token

        token = get_valid_access_token(session, "local.nonexistent", "secret")
        assert token is None


# ---------------------------------------------------------------------------
# Bitrix24Client OAuth mode
# ---------------------------------------------------------------------------

class TestClientOAuthMode:
    def test_oauth_mode_builds_url_with_auth_param(self):
        from bitrix24mcp.bitrix.client import Bitrix24Client

        client = Bitrix24Client(
            domain="example.bitrix24.ru",
            access_token="mytoken",
        )
        url, extra = client._build_url("crm.contact.list")
        assert url == "https://example.bitrix24.ru/rest/crm.contact.list"
        assert extra == {"auth": "mytoken"}

    def test_webhook_mode_builds_webhook_url(self):
        from bitrix24mcp.bitrix.client import Bitrix24Client

        client = Bitrix24Client(webhook_url="https://example.bitrix24.ru/rest/1/tok")
        url, extra = client._build_url("crm.deal.list")
        assert url == "https://example.bitrix24.ru/rest/1/tok/crm.deal.list"
        assert extra == {}

    def test_missing_credentials_raises(self):
        from bitrix24mcp.bitrix.client import Bitrix24Client

        with pytest.raises(ValueError, match="webhook_url"):
            Bitrix24Client()

    def test_oauth_mode_calls_refresher_on_401(self):
        from bitrix24mcp.bitrix.client import Bitrix24Client
        import httpx

        refresher_called = []

        def fake_refresher() -> str:
            refresher_called.append(True)
            return "newtoken"

        client = Bitrix24Client(
            domain="example.bitrix24.ru",
            access_token="expiredtoken",
            token_refresher=fake_refresher,
        )

        # First call returns 401, second returns success
        bad_resp = MagicMock()
        bad_resp.status_code = 401
        bad_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=bad_resp
        )

        good_resp = MagicMock()
        good_resp.raise_for_status.return_value = None
        good_resp.json.return_value = {"result": {"ID": "1"}}

        with patch.object(client._http, "post", side_effect=[bad_resp, good_resp]):
            result = client._request("crm.deal.get", {"id": 1})

        assert len(refresher_called) == 1
        assert client._access_token == "newtoken"
        assert result["result"]["ID"] == "1"


# ---------------------------------------------------------------------------
# MCP tool: authorize_bitrix24 and get_auth_status
# ---------------------------------------------------------------------------

class TestAuthTools:
    def test_authorize_bitrix24_no_config(self, in_memory_db):
        """Without client_id/secret, authorize_bitrix24 returns an error."""
        from bitrix24mcp.server import _dispatch
        from bitrix24mcp import config

        original_id = config.settings.bitrix24_client_id
        original_secret = config.settings.bitrix24_client_secret
        config.settings.bitrix24_client_id = ""
        config.settings.bitrix24_client_secret = ""
        try:
            result = _dispatch("authorize_bitrix24", {})
        finally:
            config.settings.bitrix24_client_id = original_id
            config.settings.bitrix24_client_secret = original_secret

        assert "error" in result
        assert "BITRIX24_CLIENT_ID" in result["error"]

    def test_get_auth_status_no_config(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        from bitrix24mcp import config

        original_wh = config.settings.bitrix24_webhook_url
        original_id = config.settings.bitrix24_client_id
        config.settings.bitrix24_webhook_url = ""
        config.settings.bitrix24_client_id = ""
        try:
            result = _dispatch("get_auth_status", {})
        finally:
            config.settings.bitrix24_webhook_url = original_wh
            config.settings.bitrix24_client_id = original_id

        assert result["active_mode"] == "none"

    def test_get_auth_status_webhook(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        from bitrix24mcp import config

        original_id = config.settings.bitrix24_client_id
        config.settings.bitrix24_client_id = ""
        try:
            result = _dispatch("get_auth_status", {})
        finally:
            config.settings.bitrix24_client_id = original_id

        assert result["webhook_config_present"] is True

    def test_get_auth_status_oauth_no_token(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        from bitrix24mcp import config

        original_id = config.settings.bitrix24_client_id
        original_secret = config.settings.bitrix24_client_secret
        config.settings.bitrix24_client_id = "local.testapp_auth"
        config.settings.bitrix24_client_secret = "testsecret"
        try:
            result = _dispatch("get_auth_status", {})
        finally:
            config.settings.bitrix24_client_id = original_id
            config.settings.bitrix24_client_secret = original_secret

        assert result["oauth_config_present"] is True
        assert result["oauth_token"] == "not_authorized"

    def test_get_auth_status_oauth_valid_token(self, in_memory_db):
        from bitrix24mcp.server import _dispatch
        from bitrix24mcp import config
        from bitrix24mcp.db.database import get_session
        from bitrix24mcp.bitrix.oauth import save_token

        client_id = "local.statustest"
        original_id = config.settings.bitrix24_client_id
        original_secret = config.settings.bitrix24_client_secret
        config.settings.bitrix24_client_id = client_id
        config.settings.bitrix24_client_secret = "testsecret"

        with get_session() as session:
            save_token(session, client_id, {
                "access_token": "tok",
                "refresh_token": "ref",
                "expires_in": 3600,
                "domain": "test.bitrix24.ru",
                "member_id": "m1",
                "scope": "crm",
            })

        try:
            result = _dispatch("get_auth_status", {})
        finally:
            config.settings.bitrix24_client_id = original_id
            config.settings.bitrix24_client_secret = original_secret

        assert result["oauth_token"] == "valid"
        assert result["domain"] == "test.bitrix24.ru"
