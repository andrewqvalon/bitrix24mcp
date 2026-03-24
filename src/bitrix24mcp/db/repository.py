"""Data-access layer – CRUD operations on the local cache."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from bitrix24mcp.db.models import (
    Activity,
    Company,
    Contact,
    Deal,
    Lead,
    Pipeline,
    Stage,
    SyncState,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(value.split("+")[0].split(".")[0], fmt.split("%z")[0])
            return dt
        except ValueError:
            continue
    return None


def _json_phones(raw: Any) -> str:
    if not raw:
        return "[]"
    if isinstance(raw, list):
        return json.dumps([p.get("VALUE", "") for p in raw if p.get("VALUE")])
    return json.dumps([str(raw)])


def _json_emails(raw: Any) -> str:
    return _json_phones(raw)  # same structure


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

def upsert_contact(session: Session, data: Dict[str, Any]) -> None:
    bid = int(data["ID"])
    obj = session.get(Contact, bid)
    if obj is None:
        obj = Contact(id=bid)
        session.add(obj)
    obj.first_name = data.get("NAME", "")
    obj.last_name = data.get("LAST_NAME", "")
    obj.second_name = data.get("SECOND_NAME", "")
    obj.name = " ".join(filter(None, [obj.first_name, obj.second_name, obj.last_name])) or f"Contact#{bid}"
    obj.phone = _json_phones(data.get("PHONE"))
    obj.email = _json_emails(data.get("EMAIL"))
    obj.company_id = int(data["COMPANY_ID"]) if data.get("COMPANY_ID") else None
    obj.assigned_by_id = int(data["ASSIGNED_BY_ID"]) if data.get("ASSIGNED_BY_ID") else None
    obj.source_id = data.get("SOURCE_ID")
    obj.comments = data.get("COMMENTS")
    obj.date_create = _parse_dt(data.get("DATE_CREATE"))
    obj.date_modify = _parse_dt(data.get("DATE_MODIFY"))
    obj.raw_json = json.dumps(data, ensure_ascii=False)


def search_contacts(
    session: Session,
    query: str = "",
    company_id: Optional[int] = None,
    limit: int = 50,
) -> List[Contact]:
    q = session.query(Contact)
    if query:
        like = f"%{query}%"
        q = q.filter(
            or_(
                Contact.name.ilike(like),
                Contact.phone.ilike(like),
                Contact.email.ilike(like),
            )
        )
    if company_id is not None:
        q = q.filter(Contact.company_id == company_id)
    return q.order_by(Contact.name).limit(limit).all()


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

def upsert_company(session: Session, data: Dict[str, Any]) -> None:
    bid = int(data["ID"])
    obj = session.get(Company, bid)
    if obj is None:
        obj = Company(id=bid)
        session.add(obj)
    obj.title = data.get("TITLE") or f"Company#{bid}"
    obj.phone = _json_phones(data.get("PHONE"))
    obj.email = _json_emails(data.get("EMAIL"))
    obj.assigned_by_id = int(data["ASSIGNED_BY_ID"]) if data.get("ASSIGNED_BY_ID") else None
    obj.industry = data.get("INDUSTRY")
    obj.employees = data.get("EMPLOYEES")
    obj.revenue = float(data["REVENUE"]) if data.get("REVENUE") else None
    obj.comments = data.get("COMMENTS")
    obj.date_create = _parse_dt(data.get("DATE_CREATE"))
    obj.date_modify = _parse_dt(data.get("DATE_MODIFY"))
    obj.raw_json = json.dumps(data, ensure_ascii=False)


def search_companies(
    session: Session,
    query: str = "",
    limit: int = 50,
) -> List[Company]:
    q = session.query(Company)
    if query:
        like = f"%{query}%"
        q = q.filter(
            or_(
                Company.title.ilike(like),
                Company.phone.ilike(like),
                Company.email.ilike(like),
            )
        )
    return q.order_by(Company.title).limit(limit).all()


# ---------------------------------------------------------------------------
# Pipelines & Stages
# ---------------------------------------------------------------------------

def upsert_pipeline(session: Session, data: Dict[str, Any]) -> None:
    bid = int(data.get("ID", data.get("id", 0)))
    obj = session.get(Pipeline, bid)
    if obj is None:
        obj = Pipeline(id=bid)
        session.add(obj)
    obj.name = data.get("NAME", data.get("name", f"Pipeline#{bid}"))
    obj.is_default = data.get("IS_DEFAULT", "N") == "Y" or bid == 0


def upsert_stage(session: Session, pipeline_id: int, data: Dict[str, Any]) -> None:
    status_id = data.get("STATUS_ID", data.get("id", ""))
    obj = session.query(Stage).filter(Stage.status_id == status_id).first()
    if obj is None:
        obj = Stage(status_id=status_id, pipeline_id=pipeline_id)
        session.add(obj)
    obj.name = data.get("NAME", "")
    obj.sort = int(data.get("SORT", 0))
    obj.is_final = data.get("SYSTEM_VALUE") in ("LOSE", "WIN", None) and data.get("TYPE") in ("FAIL", "WON")
    obj.is_won = data.get("TYPE") == "WON" or data.get("SEMANTICS") == "S"
    obj.pipeline_id = pipeline_id


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------

def upsert_deal(session: Session, data: Dict[str, Any]) -> None:
    bid = int(data["ID"])
    obj = session.get(Deal, bid)
    if obj is None:
        obj = Deal(id=bid)
        session.add(obj)
    obj.title = data.get("TITLE") or f"Deal#{bid}"
    obj.stage_id = data.get("STAGE_ID")
    obj.pipeline_id = int(data.get("CATEGORY_ID") or 0)
    obj.contact_id = int(data["CONTACT_ID"]) if data.get("CONTACT_ID") else None
    obj.company_id = int(data["COMPANY_ID"]) if data.get("COMPANY_ID") else None
    obj.assigned_by_id = int(data["ASSIGNED_BY_ID"]) if data.get("ASSIGNED_BY_ID") else None
    obj.opportunity = float(data["OPPORTUNITY"]) if data.get("OPPORTUNITY") else None
    obj.currency_id = data.get("CURRENCY_ID")
    obj.is_won = data.get("IS_WON") == "Y"
    obj.is_failed = data.get("CLOSED") == "Y" and not obj.is_won
    obj.is_closed = data.get("CLOSED") == "Y"
    obj.comments = data.get("COMMENTS")
    obj.source_id = data.get("SOURCE_ID")
    obj.date_create = _parse_dt(data.get("DATE_CREATE"))
    obj.date_modify = _parse_dt(data.get("DATE_MODIFY"))
    obj.close_date = _parse_dt(data.get("CLOSEDATE"))
    obj.raw_json = json.dumps(data, ensure_ascii=False)


def search_deals(
    session: Session,
    query: str = "",
    stage_id: Optional[str] = None,
    pipeline_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    company_id: Optional[int] = None,
    is_closed: Optional[bool] = None,
    limit: int = 100,
) -> List[Deal]:
    q = session.query(Deal)
    if query:
        like = f"%{query}%"
        q = q.filter(or_(Deal.title.ilike(like), Deal.comments.ilike(like)))
    if stage_id:
        q = q.filter(Deal.stage_id == stage_id)
    if pipeline_id is not None:
        q = q.filter(Deal.pipeline_id == pipeline_id)
    if contact_id is not None:
        q = q.filter(Deal.contact_id == contact_id)
    if company_id is not None:
        q = q.filter(Deal.company_id == company_id)
    if is_closed is not None:
        q = q.filter(Deal.is_closed == is_closed)
    return q.order_by(Deal.date_create.desc()).limit(limit).all()


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

def upsert_lead(session: Session, data: Dict[str, Any]) -> None:
    bid = int(data["ID"])
    obj = session.get(Lead, bid)
    if obj is None:
        obj = Lead(id=bid)
        session.add(obj)
    obj.title = data.get("TITLE") or f"Lead#{bid}"
    obj.first_name = data.get("NAME", "")
    obj.last_name = data.get("LAST_NAME", "")
    obj.name = " ".join(filter(None, [obj.first_name, obj.last_name])) or obj.title
    obj.phone = _json_phones(data.get("PHONE"))
    obj.email = _json_emails(data.get("EMAIL"))
    obj.status_id = data.get("STATUS_ID")
    obj.assigned_by_id = int(data["ASSIGNED_BY_ID"]) if data.get("ASSIGNED_BY_ID") else None
    obj.opportunity = float(data["OPPORTUNITY"]) if data.get("OPPORTUNITY") else None
    obj.currency_id = data.get("CURRENCY_ID")
    obj.company_id = int(data["COMPANY_ID"]) if data.get("COMPANY_ID") else None
    obj.contact_id = int(data["CONTACT_ID"]) if data.get("CONTACT_ID") else None
    obj.source_id = data.get("SOURCE_ID")
    obj.comments = data.get("COMMENTS")
    obj.date_create = _parse_dt(data.get("DATE_CREATE"))
    obj.date_modify = _parse_dt(data.get("DATE_MODIFY"))
    obj.raw_json = json.dumps(data, ensure_ascii=False)


def search_leads(
    session: Session,
    query: str = "",
    status_id: Optional[str] = None,
    limit: int = 100,
) -> List[Lead]:
    q = session.query(Lead)
    if query:
        like = f"%{query}%"
        q = q.filter(or_(Lead.title.ilike(like), Lead.name.ilike(like), Lead.phone.ilike(like), Lead.email.ilike(like)))
    if status_id:
        q = q.filter(Lead.status_id == status_id)
    return q.order_by(Lead.date_create.desc()).limit(limit).all()


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

_ACTIVITY_TYPE = {
    1: "call",
    2: "email",
    3: "meeting",
    4: "task",
    6: "event",
}


def upsert_activity(session: Session, data: Dict[str, Any]) -> None:
    bid = int(data["ID"])
    obj = session.get(Activity, bid)
    if obj is None:
        obj = Activity(id=bid)
        session.add(obj)
    type_id = int(data.get("TYPE_ID", 0))
    obj.type_id = type_id
    obj.type_name = _ACTIVITY_TYPE.get(type_id, f"type_{type_id}")
    obj.owner_type_id = int(data.get("OWNER_TYPE_ID", 0))
    obj.owner_id = int(data.get("OWNER_ID", 0))
    obj.subject = data.get("SUBJECT", "")
    obj.description = data.get("DESCRIPTION", "")
    obj.responsible_id = int(data["RESPONSIBLE_ID"]) if data.get("RESPONSIBLE_ID") else None
    obj.completed = data.get("COMPLETED") == "Y"
    obj.deadline = _parse_dt(data.get("DEADLINE"))
    obj.start_time = _parse_dt(data.get("START_TIME"))
    obj.end_time = _parse_dt(data.get("END_TIME"))
    obj.raw_json = json.dumps(data, ensure_ascii=False)


def get_timeline(
    session: Session,
    owner_type_id: int,
    owner_id: int,
    limit: int = 50,
) -> List[Activity]:
    return (
        session.query(Activity)
        .filter(Activity.owner_type_id == owner_type_id, Activity.owner_id == owner_id)
        .order_by(Activity.start_time.desc())
        .limit(limit)
        .all()
    )


# ---------------------------------------------------------------------------
# Sync state
# ---------------------------------------------------------------------------

def get_sync_state(session: Session, entity_type: str) -> Optional[SyncState]:
    return session.get(SyncState, entity_type)


def set_sync_state(session: Session, entity_type: str, last_id: int = 0) -> None:
    obj = session.get(SyncState, entity_type)
    if obj is None:
        obj = SyncState(entity_type=entity_type)
        session.add(obj)
    obj.last_sync_at = datetime.now(timezone.utc)
    obj.last_id = last_id
