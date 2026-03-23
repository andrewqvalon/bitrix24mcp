"""Unit tests for the Bitrix24 REST API client."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from bitrix24mcp.bitrix.client import Bitrix24Client, Bitrix24Error


def _make_client() -> Bitrix24Client:
    return Bitrix24Client("https://test.bitrix24.ru/rest/1/token")


# ---------------------------------------------------------------------------
# _request
# ---------------------------------------------------------------------------

class TestRequest:
    def test_success_returns_result(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": [{"ID": "1"}], "total": 1}
        mock_resp.raise_for_status.return_value = None

        with patch.object(client._http, "post", return_value=mock_resp) as mock_post:
            result = client._request("crm.contact.list", {"start": 0})

        assert result["result"] == [{"ID": "1"}]
        mock_post.assert_called_once()

    def test_error_response_raises(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "error": "NOT_FOUND",
            "error_description": "Entity not found",
        }
        mock_resp.raise_for_status.return_value = None

        with patch.object(client._http, "post", return_value=mock_resp):
            with pytest.raises(Bitrix24Error) as exc_info:
                client._request("crm.deal.get", {"id": 99999})

        assert exc_info.value.code == "NOT_FOUND"

    def test_http_500_retries(self):
        """5xx status should trigger a transport error so tenacity retries."""
        client = _make_client()
        bad_resp = MagicMock()
        bad_resp.status_code = 503
        bad_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503", request=MagicMock(), response=bad_resp
        )

        with patch.object(client._http, "post", return_value=bad_resp):
            with pytest.raises(httpx.TransportError):
                client._request("crm.deal.list")


# ---------------------------------------------------------------------------
# list_all pagination
# ---------------------------------------------------------------------------

class TestListAll:
    def test_single_page(self):
        client = _make_client()
        page = {"result": [{"ID": str(i)} for i in range(3)], "total": 3}

        with patch.object(client, "_request", return_value=page):
            items = list(client.list_all("crm.contact.list"))

        assert len(items) == 3

    def test_two_pages(self):
        client = _make_client()
        page1 = {"result": [{"ID": str(i)} for i in range(50)], "total": 70}
        page2 = {"result": [{"ID": str(i)} for i in range(50, 70)], "total": 70}

        call_count = 0

        def fake_request(method, params):
            nonlocal call_count
            call_count += 1
            return page1 if params["start"] == 0 else page2

        with patch.object(client, "_request", side_effect=fake_request):
            items = list(client.list_all("crm.contact.list"))

        assert len(items) == 70
        assert call_count == 2


# ---------------------------------------------------------------------------
# URL stripping
# ---------------------------------------------------------------------------

def test_trailing_slash_stripped():
    c = Bitrix24Client("https://example.bitrix24.ru/rest/1/tok/")
    assert c._base == "https://example.bitrix24.ru/rest/1/tok"


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

def test_context_manager_closes():
    client = _make_client()
    with patch.object(client._http, "close") as mock_close:
        with client:
            pass
    mock_close.assert_called_once()


# ---------------------------------------------------------------------------
# get_pipelines includes default
# ---------------------------------------------------------------------------

def test_get_pipelines_includes_default():
    client = _make_client()
    # Bitrix24 sometimes returns no default pipeline in the list
    resp = {"result": {"categories": [{"ID": 1, "NAME": "Sales", "IS_DEFAULT": "N"}]}}

    with patch.object(client, "_request", return_value=resp):
        pipelines = client.get_pipelines()

    ids = [int(p.get("ID", p.get("id", -1))) for p in pipelines]
    assert 0 in ids, "Default pipeline (id=0) should always be present"


def test_get_pipelines_no_duplicate_default():
    client = _make_client()
    resp = {
        "result": {
            "categories": [
                {"ID": 0, "NAME": "Default", "IS_DEFAULT": "Y"},
                {"ID": 1, "NAME": "Sales", "IS_DEFAULT": "N"},
            ]
        }
    }

    with patch.object(client, "_request", return_value=resp):
        pipelines = client.get_pipelines()

    ids = [int(p.get("ID", p.get("id", -1))) for p in pipelines]
    assert ids.count(0) == 1, "Default pipeline should appear only once"
