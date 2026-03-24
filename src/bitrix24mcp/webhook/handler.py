"""Optional HTTP webhook endpoint for real-time Bitrix24 event notifications.

Start it as a separate process alongside the MCP server:

    uvicorn bitrix24mcp.webhook.handler:app --host 0.0.0.0 --port 8080

Bitrix24 pushes event payloads to this endpoint whenever CRM entities change.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    _STARLETTE_AVAILABLE = True
except ImportError:
    _STARLETTE_AVAILABLE = False

from bitrix24mcp.bitrix.client import Bitrix24Client
from bitrix24mcp.config import settings
from bitrix24mcp.sync.syncer import CRMSyncer

_EVENT_HANDLERS = {
    "ONCRMDEALUPDATE": "deal",
    "ONCRMDEALADD": "deal",
    "ONCRMCONTACTUPDATE": "contact",
    "ONCRMCONTACTADD": "contact",
    "ONCRMCOMPANYUPDATE": "company",
    "ONCRMCOMPANYADD": "company",
    "ONCRMLEADUPDATE": "lead",
    "ONCRMLEADADD": "lead",
}


def _process_event(event: str, data: dict) -> None:
    """Pull fresh data for a single changed entity."""
    entity_type = _EVENT_HANDLERS.get(event.upper())
    if not entity_type:
        logger.debug("Ignoring unhandled event: %s", event)
        return
    fields = data.get("FIELDS", data.get("data", {}).get("FIELDS", {}))
    entity_id = fields.get("ID")
    if not entity_id:
        return
    entity_id = int(entity_id)

    client = Bitrix24Client(settings.bitrix24_webhook_url)
    syncer = CRMSyncer(client)
    try:
        if entity_type == "deal":
            syncer.refresh_deal(entity_id)
        elif entity_type == "contact":
            syncer.refresh_contact(entity_id)
        elif entity_type == "company":
            syncer.refresh_company(entity_id)
        elif entity_type == "lead":
            syncer.refresh_lead(entity_id)
    finally:
        client.close()


if _STARLETTE_AVAILABLE:
    async def _webhook_endpoint(request: Request) -> JSONResponse:
        try:
            payload = await request.form()
            payload_dict = dict(payload)
        except Exception:
            payload_dict = {}
        event = payload_dict.get("event", "")
        logger.info("Received webhook event: %s", event)
        try:
            _process_event(str(event), payload_dict)
        except Exception:
            logger.exception("Error processing webhook event %s", event)
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/webhook", _webhook_endpoint, methods=["POST"]),
        ]
    )
else:
    app = None  # type: ignore[assignment]
