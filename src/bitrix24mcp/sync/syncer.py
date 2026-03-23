"""Background synchronisation: pull all entities from Bitrix24 into local DB."""
from __future__ import annotations

import logging
from typing import List

from bitrix24mcp.bitrix.client import Bitrix24Client
from bitrix24mcp.config import settings
from bitrix24mcp.db.database import get_session
from bitrix24mcp.db.repository import (
    set_sync_state,
    upsert_activity,
    upsert_company,
    upsert_contact,
    upsert_deal,
    upsert_lead,
    upsert_pipeline,
    upsert_stage,
)

logger = logging.getLogger(__name__)


class CRMSyncer:
    """Pulls CRM data from Bitrix24 and writes to the local cache.

    Parameters
    ----------
    client:
        An initialised :class:`Bitrix24Client`.
    entities:
        Subset of entity types to sync.  Defaults to all.
    """

    ALL_ENTITIES = ["contacts", "companies", "pipelines", "deals", "leads", "activities"]

    def __init__(
        self,
        client: Bitrix24Client,
        entities: List[str] | None = None,
    ) -> None:
        self._client = client
        self._entities = [e.lower() for e in (entities or self.ALL_ENTITIES)]

    # ------------------------------------------------------------------

    def sync_all(self) -> None:
        """Full sync of all configured entity types."""
        for entity in self._entities:
            try:
                self._sync_entity(entity)
            except Exception:
                logger.exception("Failed to sync %s", entity)

    def _sync_entity(self, entity: str) -> None:
        dispatch = {
            "contacts": self._sync_contacts,
            "companies": self._sync_companies,
            "pipelines": self._sync_pipelines,
            "deals": self._sync_deals,
            "leads": self._sync_leads,
            "activities": self._sync_activities,
        }
        fn = dispatch.get(entity)
        if fn is None:
            logger.warning("Unknown entity type: %s", entity)
            return
        logger.info("Syncing %s …", entity)
        fn()
        logger.info("Done syncing %s", entity)

    # ------------------------------------------------------------------

    def _sync_contacts(self) -> None:
        with get_session() as session:
            count = 0
            for item in self._client.get_contacts():
                upsert_contact(session, item)
                count += 1
                if count % 200 == 0:
                    session.flush()
            set_sync_state(session, "contacts")
            logger.info("Synced %d contacts", count)

    def _sync_companies(self) -> None:
        with get_session() as session:
            count = 0
            for item in self._client.get_companies():
                upsert_company(session, item)
                count += 1
                if count % 200 == 0:
                    session.flush()
            set_sync_state(session, "companies")
            logger.info("Synced %d companies", count)

    def _sync_pipelines(self) -> None:
        with get_session() as session:
            pipelines = self._client.get_pipelines()
            for pipeline in pipelines:
                upsert_pipeline(session, pipeline)
                pid = int(pipeline.get("ID", pipeline.get("id", 0)))
                stages = self._client.get_stages(pid)
                for stage in stages:
                    upsert_stage(session, pid, stage)
            set_sync_state(session, "pipelines")
            logger.info("Synced %d pipelines", len(pipelines))

    def _sync_deals(self) -> None:
        with get_session() as session:
            count = 0
            for item in self._client.get_deals():
                upsert_deal(session, item)
                count += 1
                if count % 200 == 0:
                    session.flush()
            set_sync_state(session, "deals")
            logger.info("Synced %d deals", count)

    def _sync_leads(self) -> None:
        with get_session() as session:
            count = 0
            for item in self._client.get_leads():
                upsert_lead(session, item)
                count += 1
                if count % 200 == 0:
                    session.flush()
            set_sync_state(session, "leads")
            logger.info("Synced %d leads", count)

    def _sync_activities(self) -> None:
        """Sync activities for all entity types."""
        with get_session() as session:
            count = 0
            # owner_type_id: 1=lead, 2=deal, 3=contact, 4=company
            for owner_type_id in (1, 2, 3, 4):
                for item in self._client.get_activities(owner_type_id=owner_type_id):
                    upsert_activity(session, item)
                    count += 1
                    if count % 200 == 0:
                        session.flush()
            set_sync_state(session, "activities")
            logger.info("Synced %d activities", count)

    # ------------------------------------------------------------------
    # Single-entity refresh (used by webhook handler)
    # ------------------------------------------------------------------

    def refresh_contact(self, contact_id: int) -> None:
        data = self._client.get_contact(contact_id)
        with get_session() as session:
            upsert_contact(session, data)

    def refresh_company(self, company_id: int) -> None:
        data = self._client.get_company(company_id)
        with get_session() as session:
            upsert_company(session, data)

    def refresh_deal(self, deal_id: int) -> None:
        data = self._client.get_deal(deal_id)
        with get_session() as session:
            upsert_deal(session, data)

    def refresh_lead(self, lead_id: int) -> None:
        data = self._client.get_lead(lead_id)
        with get_session() as session:
            upsert_lead(session, data)
