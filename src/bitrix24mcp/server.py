"""MCP server exposing Bitrix24 CRM tools to AI agents.

All read operations are served from the local PostgreSQL cache.
Write operations write through to Bitrix24 and then update the cache.

Available tools
---------------
sync_crm_data          – pull fresh data from Bitrix24 into the local cache
find_contacts          – full-text search for contacts
get_contact            – get full contact record by ID
find_companies         – full-text search for companies
get_company            – get full company record by ID
find_deals             – filter / search deals
get_deal               – get full deal record by ID
find_leads             – filter / search leads
get_lead               – get full lead record by ID
list_pipelines         – list all CRM funnels / deal categories
get_deal_stages        – list stages for a specific pipeline
get_client_summary     – aggregated overview for a contact or company
get_crm_timeline       – activity timeline for a contact / company / deal
create_contact         – add a new contact in Bitrix24 + cache
create_deal            – add a new deal in Bitrix24 + cache
update_deal_stage      – move a deal to a new stage
create_lead            – add a new lead in Bitrix24 + cache
add_crm_comment        – append a comment to the CRM timeline
get_portfolio_report   – portfolio-wide statistics
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from bitrix24mcp.bitrix.client import Bitrix24Client, Bitrix24Error
from bitrix24mcp.config import settings
from bitrix24mcp.db.database import get_session, init_db
from bitrix24mcp.db.models import Activity, Company, Contact, Deal, Lead, Pipeline, Stage
from bitrix24mcp.db.repository import (
    get_timeline,
    search_companies,
    search_contacts,
    search_deals,
    search_leads,
    upsert_contact,
    upsert_deal,
    upsert_lead,
)
from bitrix24mcp.sync.syncer import CRMSyncer

logger = logging.getLogger(__name__)

server = Server("bitrix24mcp")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _contact_to_dict(c: Contact) -> Dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "first_name": c.first_name,
        "last_name": c.last_name,
        "phone": json.loads(c.phone or "[]"),
        "email": json.loads(c.email or "[]"),
        "company_id": c.company_id,
        "assigned_by_id": c.assigned_by_id,
        "source_id": c.source_id,
        "comments": c.comments,
        "date_create": _dt(c.date_create),
        "date_modify": _dt(c.date_modify),
    }


def _company_to_dict(c: Company) -> Dict[str, Any]:
    return {
        "id": c.id,
        "title": c.title,
        "phone": json.loads(c.phone or "[]"),
        "email": json.loads(c.email or "[]"),
        "assigned_by_id": c.assigned_by_id,
        "industry": c.industry,
        "employees": c.employees,
        "revenue": c.revenue,
        "comments": c.comments,
        "date_create": _dt(c.date_create),
        "date_modify": _dt(c.date_modify),
    }


def _deal_to_dict(d: Deal) -> Dict[str, Any]:
    return {
        "id": d.id,
        "title": d.title,
        "stage_id": d.stage_id,
        "pipeline_id": d.pipeline_id,
        "contact_id": d.contact_id,
        "company_id": d.company_id,
        "assigned_by_id": d.assigned_by_id,
        "opportunity": d.opportunity,
        "currency_id": d.currency_id,
        "is_won": d.is_won,
        "is_failed": d.is_failed,
        "is_closed": d.is_closed,
        "comments": d.comments,
        "source_id": d.source_id,
        "date_create": _dt(d.date_create),
        "date_modify": _dt(d.date_modify),
        "close_date": _dt(d.close_date),
    }


def _lead_to_dict(lead: Lead) -> Dict[str, Any]:
    return {
        "id": lead.id,
        "title": lead.title,
        "name": lead.name,
        "phone": json.loads(lead.phone or "[]"),
        "email": json.loads(lead.email or "[]"),
        "status_id": lead.status_id,
        "assigned_by_id": lead.assigned_by_id,
        "opportunity": lead.opportunity,
        "currency_id": lead.currency_id,
        "company_id": lead.company_id,
        "contact_id": lead.contact_id,
        "source_id": lead.source_id,
        "comments": lead.comments,
        "date_create": _dt(lead.date_create),
        "date_modify": _dt(lead.date_modify),
    }


def _activity_to_dict(a: Activity) -> Dict[str, Any]:
    return {
        "id": a.id,
        "type_id": a.type_id,
        "type_name": a.type_name,
        "owner_type_id": a.owner_type_id,
        "owner_id": a.owner_id,
        "subject": a.subject,
        "description": a.description,
        "responsible_id": a.responsible_id,
        "completed": a.completed,
        "deadline": _dt(a.deadline),
        "start_time": _dt(a.start_time),
        "end_time": _dt(a.end_time),
    }


def _get_client() -> Bitrix24Client:
    if not settings.bitrix24_webhook_url:
        raise RuntimeError(
            "BITRIX24_WEBHOOK_URL is not configured. "
            "Please set it in the .env file or environment."
        )
    return Bitrix24Client(settings.bitrix24_webhook_url)


def _text(obj: Any) -> types.TextContent:
    if isinstance(obj, str):
        text = obj
    else:
        text = json.dumps(obj, ensure_ascii=False, default=str, indent=2)
    return types.TextContent(type="text", text=text)


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name="sync_crm_data",
            description=(
                "Pull fresh data from Bitrix24 into the local cache. "
                "Optionally restrict to specific entity types. "
                "Should be called periodically or when data seems stale."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Entity types to sync. "
                            "Options: contacts, companies, deals, leads, pipelines, activities. "
                            "Defaults to all."
                        ),
                    }
                },
            },
        ),
        types.Tool(
            name="find_contacts",
            description="Search for CRM contacts by name, phone, or e-mail.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text (name, phone, or email)."},
                    "company_id": {"type": "integer", "description": "Filter by company ID."},
                    "limit": {"type": "integer", "description": "Max results (default 50)."},
                },
            },
        ),
        types.Tool(
            name="get_contact",
            description="Get the full cached record for a CRM contact by ID.",
            inputSchema={
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "integer"}},
            },
        ),
        types.Tool(
            name="find_companies",
            description="Search for CRM companies by name, phone, or e-mail.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text."},
                    "limit": {"type": "integer", "description": "Max results (default 50)."},
                },
            },
        ),
        types.Tool(
            name="get_company",
            description="Get the full cached record for a CRM company by ID.",
            inputSchema={
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "integer"}},
            },
        ),
        types.Tool(
            name="find_deals",
            description="Search or filter CRM deals.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Full-text search in title / comments."},
                    "stage_id": {"type": "string", "description": "Exact stage ID (e.g. 'NEW')."},
                    "pipeline_id": {"type": "integer", "description": "Filter by funnel / category ID."},
                    "contact_id": {"type": "integer", "description": "Filter by linked contact."},
                    "company_id": {"type": "integer", "description": "Filter by linked company."},
                    "is_closed": {"type": "boolean", "description": "True = closed deals only, False = open only."},
                    "limit": {"type": "integer", "description": "Max results (default 100)."},
                },
            },
        ),
        types.Tool(
            name="get_deal",
            description="Get the full cached record for a CRM deal by ID.",
            inputSchema={
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "integer"}},
            },
        ),
        types.Tool(
            name="find_leads",
            description="Search or filter CRM leads.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Full-text search in title / name / contacts."},
                    "status_id": {"type": "string", "description": "Exact lead status ID."},
                    "limit": {"type": "integer", "description": "Max results (default 100)."},
                },
            },
        ),
        types.Tool(
            name="get_lead",
            description="Get the full cached record for a CRM lead by ID.",
            inputSchema={
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "integer"}},
            },
        ),
        types.Tool(
            name="list_pipelines",
            description="List all CRM funnels (deal categories).",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_deal_stages",
            description="List the stages for a specific CRM pipeline / funnel.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pipeline_id": {
                        "type": "integer",
                        "description": "Pipeline ID (0 = default funnel).",
                    }
                },
            },
        ),
        types.Tool(
            name="get_client_summary",
            description=(
                "Return an aggregated summary for a client (contact or company): "
                "number of deals, total opportunity, open deals, last activity date."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer", "description": "Contact ID."},
                    "company_id": {"type": "integer", "description": "Company ID."},
                },
            },
        ),
        types.Tool(
            name="get_crm_timeline",
            description=(
                "Return the CRM activity timeline for a contact, company, deal, or lead. "
                "Shows calls, emails, meetings, notes, and other events."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "One of: contact, company, deal, lead.",
                    },
                    "entity_id": {"type": "integer", "description": "Entity ID."},
                    "limit": {"type": "integer", "description": "Max events (default 50)."},
                },
                "required": ["entity_type", "entity_id"],
            },
        ),
        types.Tool(
            name="create_contact",
            description="Create a new CRM contact in Bitrix24 and add it to the local cache.",
            inputSchema={
                "type": "object",
                "required": ["first_name"],
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "phone": {
                        "type": "string",
                        "description": "Primary phone number.",
                    },
                    "email": {"type": "string", "description": "Primary e-mail address."},
                    "company_id": {"type": "integer"},
                    "comments": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="create_deal",
            description="Create a new CRM deal in Bitrix24 and add it to the local cache.",
            inputSchema={
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string"},
                    "pipeline_id": {"type": "integer", "description": "Funnel / category ID (0 = default)."},
                    "stage_id": {"type": "string", "description": "Initial stage ID."},
                    "contact_id": {"type": "integer"},
                    "company_id": {"type": "integer"},
                    "opportunity": {"type": "number", "description": "Deal value."},
                    "currency_id": {"type": "string", "description": "Currency code (e.g. RUB, USD)."},
                    "comments": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="update_deal_stage",
            description="Move a CRM deal to a different stage.",
            inputSchema={
                "type": "object",
                "required": ["deal_id", "stage_id"],
                "properties": {
                    "deal_id": {"type": "integer"},
                    "stage_id": {"type": "string", "description": "Target stage ID."},
                    "comment": {"type": "string", "description": "Optional comment to add to the timeline."},
                },
            },
        ),
        types.Tool(
            name="create_lead",
            description="Create a new CRM lead in Bitrix24 and add it to the local cache.",
            inputSchema={
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string"},
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "opportunity": {"type": "number"},
                    "currency_id": {"type": "string"},
                    "source_id": {"type": "string", "description": "Lead source (e.g. WEB, CALL)."},
                    "comments": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="add_crm_comment",
            description="Add a comment / note to the CRM timeline of a contact, company, deal, or lead.",
            inputSchema={
                "type": "object",
                "required": ["entity_type", "entity_id", "comment"],
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "One of: contact, company, deal, lead.",
                    },
                    "entity_id": {"type": "integer"},
                    "comment": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="get_portfolio_report",
            description=(
                "Return a portfolio-wide report: total deals, pipeline breakdown, "
                "total opportunity, open vs closed deals, recent activity count."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "pipeline_id": {
                        "type": "integer",
                        "description": "Restrict report to a single pipeline (optional).",
                    }
                },
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
    try:
        result = _dispatch(name, arguments)
        return [_text(result)]
    except Bitrix24Error as exc:
        return [_text({"error": str(exc), "code": exc.code})]
    except Exception as exc:
        logger.exception("Tool %s raised an exception", name)
        return [_text({"error": str(exc)})]


def _dispatch(name: str, args: Dict[str, Any]) -> Any:
    handlers = {
        "sync_crm_data": _tool_sync_crm_data,
        "find_contacts": _tool_find_contacts,
        "get_contact": _tool_get_contact,
        "find_companies": _tool_find_companies,
        "get_company": _tool_get_company,
        "find_deals": _tool_find_deals,
        "get_deal": _tool_get_deal,
        "find_leads": _tool_find_leads,
        "get_lead": _tool_get_lead,
        "list_pipelines": _tool_list_pipelines,
        "get_deal_stages": _tool_get_deal_stages,
        "get_client_summary": _tool_get_client_summary,
        "get_crm_timeline": _tool_get_crm_timeline,
        "create_contact": _tool_create_contact,
        "create_deal": _tool_create_deal,
        "update_deal_stage": _tool_update_deal_stage,
        "create_lead": _tool_create_lead,
        "add_crm_comment": _tool_add_crm_comment,
        "get_portfolio_report": _tool_get_portfolio_report,
    }
    fn = handlers.get(name)
    if fn is None:
        raise ValueError(f"Unknown tool: {name}")
    return fn(args)


# ------------------------------------------------------------------
# Sync
# ------------------------------------------------------------------

def _tool_sync_crm_data(args: Dict[str, Any]) -> Dict[str, Any]:
    entities = args.get("entities") or settings.entity_list()
    client = _get_client()
    syncer = CRMSyncer(client, entities=entities)
    try:
        syncer.sync_all()
    finally:
        client.close()
    return {"status": "ok", "synced_entities": entities}


# ------------------------------------------------------------------
# Contacts
# ------------------------------------------------------------------

def _tool_find_contacts(args: Dict[str, Any]) -> List[Dict]:
    with get_session() as session:
        results = search_contacts(
            session,
            query=args.get("query", ""),
            company_id=args.get("company_id"),
            limit=int(args.get("limit", 50)),
        )
        return [_contact_to_dict(c) for c in results]


def _tool_get_contact(args: Dict[str, Any]) -> Dict:
    with get_session() as session:
        obj = session.get(Contact, int(args["id"]))
        if obj is None:
            return {"error": f"Contact {args['id']} not found in cache. Run sync_crm_data first."}
        return _contact_to_dict(obj)


# ------------------------------------------------------------------
# Companies
# ------------------------------------------------------------------

def _tool_find_companies(args: Dict[str, Any]) -> List[Dict]:
    with get_session() as session:
        results = search_companies(
            session,
            query=args.get("query", ""),
            limit=int(args.get("limit", 50)),
        )
        return [_company_to_dict(c) for c in results]


def _tool_get_company(args: Dict[str, Any]) -> Dict:
    with get_session() as session:
        obj = session.get(Company, int(args["id"]))
        if obj is None:
            return {"error": f"Company {args['id']} not found in cache. Run sync_crm_data first."}
        return _company_to_dict(obj)


# ------------------------------------------------------------------
# Deals
# ------------------------------------------------------------------

def _tool_find_deals(args: Dict[str, Any]) -> List[Dict]:
    with get_session() as session:
        results = search_deals(
            session,
            query=args.get("query", ""),
            stage_id=args.get("stage_id"),
            pipeline_id=args.get("pipeline_id"),
            contact_id=args.get("contact_id"),
            company_id=args.get("company_id"),
            is_closed=args.get("is_closed"),
            limit=int(args.get("limit", 100)),
        )
        return [_deal_to_dict(d) for d in results]


def _tool_get_deal(args: Dict[str, Any]) -> Dict:
    with get_session() as session:
        obj = session.get(Deal, int(args["id"]))
        if obj is None:
            return {"error": f"Deal {args['id']} not found in cache. Run sync_crm_data first."}
        return _deal_to_dict(obj)


# ------------------------------------------------------------------
# Leads
# ------------------------------------------------------------------

def _tool_find_leads(args: Dict[str, Any]) -> List[Dict]:
    with get_session() as session:
        results = search_leads(
            session,
            query=args.get("query", ""),
            status_id=args.get("status_id"),
            limit=int(args.get("limit", 100)),
        )
        return [_lead_to_dict(lead) for lead in results]


def _tool_get_lead(args: Dict[str, Any]) -> Dict:
    with get_session() as session:
        obj = session.get(Lead, int(args["id"]))
        if obj is None:
            return {"error": f"Lead {args['id']} not found in cache. Run sync_crm_data first."}
        return _lead_to_dict(obj)


# ------------------------------------------------------------------
# Pipelines & Stages
# ------------------------------------------------------------------

def _tool_list_pipelines(args: Dict[str, Any]) -> List[Dict]:
    with get_session() as session:
        pipelines = session.query(Pipeline).order_by(Pipeline.id).all()
        if not pipelines:
            return [{"info": "No pipelines cached. Run sync_crm_data first."}]
        return [
            {"id": p.id, "name": p.name, "is_default": p.is_default}
            for p in pipelines
        ]


def _tool_get_deal_stages(args: Dict[str, Any]) -> List[Dict]:
    pipeline_id = int(args.get("pipeline_id", 0))
    with get_session() as session:
        stages = (
            session.query(Stage)
            .filter(Stage.pipeline_id == pipeline_id)
            .order_by(Stage.sort)
            .all()
        )
        if not stages:
            return [{"info": f"No stages cached for pipeline {pipeline_id}. Run sync_crm_data first."}]
        return [
            {
                "status_id": s.status_id,
                "name": s.name,
                "sort": s.sort,
                "is_final": s.is_final,
                "is_won": s.is_won,
            }
            for s in stages
        ]


# ------------------------------------------------------------------
# Client summary
# ------------------------------------------------------------------

def _tool_get_client_summary(args: Dict[str, Any]) -> Dict:
    contact_id: Optional[int] = args.get("contact_id")
    company_id: Optional[int] = args.get("company_id")
    if not contact_id and not company_id:
        return {"error": "Provide at least one of: contact_id, company_id"}

    with get_session() as session:
        contact: Optional[Contact] = None
        company: Optional[Company] = None

        if contact_id:
            contact = session.get(Contact, contact_id)
        if company_id:
            company = session.get(Company, company_id)

        # Deals linked to this client
        deal_filters: Dict[str, Any] = {}
        if contact_id:
            deal_filters["contact_id"] = contact_id
        if company_id:
            deal_filters["company_id"] = company_id

        deals = search_deals(session, limit=1000, **deal_filters)
        open_deals = [d for d in deals if not d.is_closed]
        won_deals = [d for d in deals if d.is_won]
        total_opp = sum(d.opportunity or 0 for d in deals)
        open_opp = sum(d.opportunity or 0 for d in open_deals)

        # Last activity
        owner_type_id = 3 if contact_id else 4
        owner_id = contact_id or company_id
        last_activities = get_timeline(session, owner_type_id=owner_type_id, owner_id=owner_id, limit=1)  # type: ignore[arg-type]
        last_activity_date = None
        if last_activities:
            last_activity_date = _dt(last_activities[0].start_time or last_activities[0].updated_at)

        return {
            "contact": _contact_to_dict(contact) if contact else None,
            "company": _company_to_dict(company) if company else None,
            "deals": {
                "total": len(deals),
                "open": len(open_deals),
                "won": len(won_deals),
                "lost": len(deals) - len(open_deals) - len(won_deals),
                "total_opportunity": total_opp,
                "open_opportunity": open_opp,
            },
            "last_activity_date": last_activity_date,
        }


# ------------------------------------------------------------------
# Timeline
# ------------------------------------------------------------------

_OWNER_TYPE_MAP = {
    "lead": 1,
    "deal": 2,
    "contact": 3,
    "company": 4,
}


def _tool_get_crm_timeline(args: Dict[str, Any]) -> List[Dict]:
    entity_type = str(args.get("entity_type", "deal")).lower()
    entity_id = int(args["entity_id"])
    limit = int(args.get("limit", 50))
    owner_type_id = _OWNER_TYPE_MAP.get(entity_type, 2)
    with get_session() as session:
        activities = get_timeline(session, owner_type_id=owner_type_id, owner_id=entity_id, limit=limit)
        if not activities:
            return [{"info": "No activities in cache for this entity. Run sync_crm_data first."}]
        return [_activity_to_dict(a) for a in activities]


# ------------------------------------------------------------------
# Mutations – Contact
# ------------------------------------------------------------------

def _tool_create_contact(args: Dict[str, Any]) -> Dict:
    fields: Dict[str, Any] = {
        "NAME": args.get("first_name", ""),
        "LAST_NAME": args.get("last_name", ""),
    }
    if args.get("phone"):
        fields["PHONE"] = [{"VALUE": args["phone"], "VALUE_TYPE": "WORK"}]
    if args.get("email"):
        fields["EMAIL"] = [{"VALUE": args["email"], "VALUE_TYPE": "WORK"}]
    if args.get("company_id"):
        fields["COMPANY_ID"] = args["company_id"]
    if args.get("comments"):
        fields["COMMENTS"] = args["comments"]

    client = _get_client()
    try:
        new_id = client.create_contact(fields)
        fresh = client.get_contact(new_id)
    finally:
        client.close()

    with get_session() as session:
        upsert_contact(session, fresh)

    return {"id": new_id, "status": "created"}


# ------------------------------------------------------------------
# Mutations – Deal
# ------------------------------------------------------------------

def _tool_create_deal(args: Dict[str, Any]) -> Dict:
    fields: Dict[str, Any] = {"TITLE": args["title"]}
    for key, field in [
        ("pipeline_id", "CATEGORY_ID"),
        ("stage_id", "STAGE_ID"),
        ("contact_id", "CONTACT_ID"),
        ("company_id", "COMPANY_ID"),
        ("opportunity", "OPPORTUNITY"),
        ("currency_id", "CURRENCY_ID"),
        ("comments", "COMMENTS"),
    ]:
        if args.get(key) is not None:
            fields[field] = args[key]

    client = _get_client()
    try:
        new_id = client.create_deal(fields)
        fresh = client.get_deal(new_id)
    finally:
        client.close()

    with get_session() as session:
        upsert_deal(session, fresh)

    return {"id": new_id, "status": "created"}


def _tool_update_deal_stage(args: Dict[str, Any]) -> Dict:
    deal_id = int(args["deal_id"])
    stage_id = str(args["stage_id"])
    comment = args.get("comment")

    client = _get_client()
    try:
        ok = client.update_deal(deal_id, {"STAGE_ID": stage_id})
        if comment:
            client.add_timeline_comment("deal", deal_id, comment)
        fresh = client.get_deal(deal_id)
    finally:
        client.close()

    with get_session() as session:
        upsert_deal(session, fresh)

    return {"deal_id": deal_id, "new_stage_id": stage_id, "success": ok}


# ------------------------------------------------------------------
# Mutations – Lead
# ------------------------------------------------------------------

def _tool_create_lead(args: Dict[str, Any]) -> Dict:
    fields: Dict[str, Any] = {"TITLE": args["title"]}
    for key, field in [
        ("first_name", "NAME"),
        ("last_name", "LAST_NAME"),
        ("opportunity", "OPPORTUNITY"),
        ("currency_id", "CURRENCY_ID"),
        ("source_id", "SOURCE_ID"),
        ("comments", "COMMENTS"),
    ]:
        if args.get(key) is not None:
            fields[field] = args[key]
    if args.get("phone"):
        fields["PHONE"] = [{"VALUE": args["phone"], "VALUE_TYPE": "WORK"}]
    if args.get("email"):
        fields["EMAIL"] = [{"VALUE": args["email"], "VALUE_TYPE": "WORK"}]

    client = _get_client()
    try:
        new_id = client.create_lead(fields)
        fresh = client.get_lead(new_id)
    finally:
        client.close()

    with get_session() as session:
        upsert_lead(session, fresh)

    return {"id": new_id, "status": "created"}


# ------------------------------------------------------------------
# Mutations – Comment
# ------------------------------------------------------------------

def _tool_add_crm_comment(args: Dict[str, Any]) -> Dict:
    entity_type = str(args["entity_type"]).lower()
    entity_id = int(args["entity_id"])
    comment = str(args["comment"])

    client = _get_client()
    try:
        comment_id = client.add_timeline_comment(entity_type, entity_id, comment)
    finally:
        client.close()

    return {"comment_id": comment_id, "status": "added"}


# ------------------------------------------------------------------
# Portfolio report
# ------------------------------------------------------------------

def _tool_get_portfolio_report(args: Dict[str, Any]) -> Dict:
    pipeline_id: Optional[int] = args.get("pipeline_id")
    with get_session() as session:
        q = session.query(Deal)
        if pipeline_id is not None:
            q = q.filter(Deal.pipeline_id == pipeline_id)
        deals = q.all()

        total = len(deals)
        open_deals = [d for d in deals if not d.is_closed]
        won_deals = [d for d in deals if d.is_won]
        lost_deals = [d for d in deals if d.is_closed and not d.is_won]
        total_opp = sum(d.opportunity or 0 for d in deals)
        open_opp = sum(d.opportunity or 0 for d in open_deals)

        # Breakdown by stage
        stage_breakdown: Dict[str, int] = {}
        for d in open_deals:
            stage_breakdown[d.stage_id or "UNKNOWN"] = stage_breakdown.get(d.stage_id or "UNKNOWN", 0) + 1

        # Breakdown by pipeline
        pipeline_breakdown: Dict[str, Dict] = {}
        for d in deals:
            pid = str(d.pipeline_id)
            if pid not in pipeline_breakdown:
                pipeline_breakdown[pid] = {"total": 0, "open": 0, "won": 0, "opportunity": 0}
            pipeline_breakdown[pid]["total"] += 1
            if not d.is_closed:
                pipeline_breakdown[pid]["open"] += 1
            if d.is_won:
                pipeline_breakdown[pid]["won"] += 1
            pipeline_breakdown[pid]["opportunity"] += d.opportunity or 0

        return {
            "pipeline_id": pipeline_id,
            "summary": {
                "total_deals": total,
                "open_deals": len(open_deals),
                "won_deals": len(won_deals),
                "lost_deals": len(lost_deals),
                "total_opportunity": total_opp,
                "open_opportunity": open_opp,
            },
            "stage_breakdown": stage_breakdown,
            "pipeline_breakdown": pipeline_breakdown,
        }


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

async def run() -> None:
    """Initialise the DB and start the MCP server over stdio."""
    init_db()
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
