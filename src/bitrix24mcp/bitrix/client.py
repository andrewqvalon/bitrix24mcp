"""Bitrix24 REST API client.

Handles:
- Webhook-based authentication (no OAuth needed for read-only / single-tenant use).
- Automatic pagination via ``start`` parameter.
- Retry on transient errors (5xx, timeouts) with exponential back-off.
- Rate limiting: Bitrix24 allows 2 req/s; we honour that conservatively.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Generator, List, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Bitrix24 returns at most 50 records per page
_PAGE_SIZE = 50


class Bitrix24Error(Exception):
    """Raised when Bitrix24 returns an error response."""

    def __init__(self, code: str, description: str) -> None:
        super().__init__(f"Bitrix24 API error [{code}]: {description}")
        self.code = code
        self.description = description


class Bitrix24Client:
    """Thin wrapper around Bitrix24 REST endpoints.

    Parameters
    ----------
    webhook_url:
        Base URL for an incoming webhook, e.g.
        ``https://example.bitrix24.ru/rest/1/TOKEN``.
        A trailing slash is optional – it will be stripped.
    timeout:
        HTTP timeout in seconds for individual requests.
    """

    def __init__(self, webhook_url: str, timeout: float = 30.0) -> None:
        self._base = webhook_url.rstrip("/")
        self._http = httpx.Client(timeout=timeout)
        self._last_call: float = 0.0

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        """Ensure at least 0.5 s between successive calls (≤ 2 req/s)."""
        elapsed = time.monotonic() - self._last_call
        if elapsed < 0.5:
            time.sleep(0.5 - elapsed)

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Make a single Bitrix24 REST call and return parsed JSON result."""
        self._throttle()
        url = f"{self._base}/{method}"
        self._last_call = time.monotonic()
        try:
            resp = self._http.post(url, json=params or {})
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                # Raise as TransportError so tenacity retries
                raise httpx.TransportError(str(exc)) from exc
            raise
        data = resp.json()
        if "error" in data:
            raise Bitrix24Error(
                data.get("error", "UNKNOWN"),
                data.get("error_description", ""),
            )
        return data

    # ------------------------------------------------------------------
    # Paginated list helpers
    # ------------------------------------------------------------------

    def list_all(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        result_key: str = "result",
    ) -> Generator[Dict[str, Any], None, None]:
        """Iterate over *all* pages for a list method, yielding individual items."""
        params = dict(params or {})
        params.setdefault("order", {"ID": "ASC"})
        start = 0
        while True:
            params["start"] = start
            data = self._request(method, params)
            items: List[Dict[str, Any]] = data.get(result_key, [])
            yield from items
            total = int(data.get("total", 0))
            start += _PAGE_SIZE
            if start >= total or not items:
                break

    # ------------------------------------------------------------------
    # Public API – CRM entities
    # ------------------------------------------------------------------

    def get_contacts(self, select: Optional[List[str]] = None, **filters: Any) -> Generator[Dict, None, None]:
        params: Dict[str, Any] = {
            "select": select or ["*", "PHONE", "EMAIL"],
        }
        if filters:
            params["filter"] = filters
        yield from self.list_all("crm.contact.list", params)

    def get_contact(self, contact_id: int) -> Dict[str, Any]:
        data = self._request("crm.contact.get", {"id": contact_id})
        return data["result"]

    def get_companies(self, select: Optional[List[str]] = None, **filters: Any) -> Generator[Dict, None, None]:
        params: Dict[str, Any] = {
            "select": select or ["*", "PHONE", "EMAIL"],
        }
        if filters:
            params["filter"] = filters
        yield from self.list_all("crm.company.list", params)

    def get_company(self, company_id: int) -> Dict[str, Any]:
        data = self._request("crm.company.get", {"id": company_id})
        return data["result"]

    def get_deals(self, select: Optional[List[str]] = None, **filters: Any) -> Generator[Dict, None, None]:
        params: Dict[str, Any] = {"select": select or ["*"]}
        if filters:
            params["filter"] = filters
        yield from self.list_all("crm.deal.list", params)

    def get_deal(self, deal_id: int) -> Dict[str, Any]:
        data = self._request("crm.deal.get", {"id": deal_id})
        return data["result"]

    def get_leads(self, select: Optional[List[str]] = None, **filters: Any) -> Generator[Dict, None, None]:
        params: Dict[str, Any] = {"select": select or ["*", "PHONE", "EMAIL"]}
        if filters:
            params["filter"] = filters
        yield from self.list_all("crm.lead.list", params)

    def get_lead(self, lead_id: int) -> Dict[str, Any]:
        data = self._request("crm.lead.get", {"id": lead_id})
        return data["result"]

    def get_pipelines(self) -> List[Dict[str, Any]]:
        """Return all deal categories (funnels)."""
        data = self._request("crm.category.list", {"entityTypeId": 2})
        categories = data.get("result", {}).get("categories", data.get("result", []))
        # Bitrix24 returns {"result": {"categories": [...]}} for this endpoint
        if isinstance(categories, dict):
            categories = categories.get("categories", [])
        # Ensure the default pipeline (id=0) is present
        default_found = any(str(c.get("ID", c.get("id", ""))) == "0" for c in categories)
        if not default_found:
            categories = [{"ID": 0, "NAME": "Default", "IS_DEFAULT": "Y"}] + categories
        return categories

    def get_stages(self, pipeline_id: int = 0) -> List[Dict[str, Any]]:
        data = self._request(
            "crm.dealcategory.stage.list",
            {"id": pipeline_id},
        )
        return data.get("result", [])

    def get_activities(
        self,
        owner_type_id: int = 2,
        owner_id: Optional[int] = None,
        select: Optional[List[str]] = None,
    ) -> Generator[Dict, None, None]:
        """Fetch CRM activities (calls, emails, meetings, notes, etc.).

        Parameters
        ----------
        owner_type_id:
            2 = Deal, 3 = Contact, 4 = Company, 1 = Lead
        owner_id:
            Specific owner entity ID; if None all activities are fetched.
        """
        params: Dict[str, Any] = {
            "select": select or ["*"],
            "filter": {"OWNER_TYPE_ID": owner_type_id},
        }
        if owner_id is not None:
            params["filter"]["OWNER_ID"] = owner_id
        yield from self.list_all("crm.activity.list", params)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def create_contact(self, fields: Dict[str, Any]) -> int:
        data = self._request("crm.contact.add", {"fields": fields})
        return int(data["result"])

    def create_company(self, fields: Dict[str, Any]) -> int:
        data = self._request("crm.company.add", {"fields": fields})
        return int(data["result"])

    def create_deal(self, fields: Dict[str, Any]) -> int:
        data = self._request("crm.deal.add", {"fields": fields})
        return int(data["result"])

    def update_deal(self, deal_id: int, fields: Dict[str, Any]) -> bool:
        data = self._request("crm.deal.update", {"id": deal_id, "fields": fields})
        return bool(data.get("result"))

    def create_lead(self, fields: Dict[str, Any]) -> int:
        data = self._request("crm.lead.add", {"fields": fields})
        return int(data["result"])

    def add_timeline_comment(self, entity_type: str, entity_id: int, comment: str) -> int:
        """Add a comment to the CRM timeline.

        Parameters
        ----------
        entity_type:
            ``"deal"``, ``"contact"``, ``"company"``, or ``"lead"``.
        entity_id:
            ID of the owning entity.
        comment:
            Comment text.
        """
        entity_type_map = {
            "deal": 2,
            "contact": 3,
            "company": 4,
            "lead": 1,
        }
        owner_type_id = entity_type_map.get(entity_type.lower(), 2)
        data = self._request(
            "crm.timeline.comment.add",
            {
                "fields": {
                    "ENTITY_TYPE": entity_type.upper(),
                    "ENTITY_ID": entity_id,
                    "COMMENT": comment,
                    "OWNER_TYPE_ID": owner_type_id,
                    "OWNER_ID": entity_id,
                }
            },
        )
        return int(data.get("result", 0))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Bitrix24Client":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
