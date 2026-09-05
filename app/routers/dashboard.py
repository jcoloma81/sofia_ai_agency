import re
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.prospect import Prospect
from app.services import whatsapp
from app.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()

class ManualMessagePayload(BaseModel):
    text: str

class BulkImportItem(BaseModel):
    phone: str
    name: str
    contact_name: Optional[str] = None
    city: Optional[str] = None
    business_type: Optional[str] = None

class BulkImportRequest(BaseModel):
    leads: List[BulkImportItem]
    start_immediately: bool = False

@router.get("/api/v1/dashboard/metrics")
def get_dashboard_metrics(db: Session = Depends(get_db)):
    """Returns real-time KPIs and system status for the dashboard."""
    total = db.query(Prospect).count()
    meetings = db.query(Prospect).filter(Prospect.status == "meeting_scheduled").count()
    in_conversation = db.query(Prospect).filter(Prospect.status == "in_conversation").count()
    human_takeover = db.query(Prospect).filter(Prospect.status == "human_takeover").count()
    contacted = db.query(Prospect).filter(Prospect.status == "contacted").count()

    from app.services.pacing import is_within_business_hours, get_daily_outreaches_count, MAX_DAILY_OUTREACH, get_current_argentine_time
    daily_count = get_daily_outreaches_count(db)
    business_hours_open = is_within_business_hours()
    now_arg = get_current_argentine_time()

    return {
        "total_prospects": total,
        "meetings_scheduled": meetings,
        "in_conversation": in_conversation,
        "human_takeover": human_takeover,
        "contacted": contacted,
        "conversion_rate": round((meetings / total * 100) if total > 0 else 0, 1),
        "daily_outreach_count": daily_count,
        "daily_outreach_max": MAX_DAILY_OUTREACH,
        "business_hours_open": business_hours_open,
        "argentine_time": now_arg.strftime("%H:%M hs"),
        "agent_name": "Sofía B2B SDR",
        "agent_phone": settings.WHATSAPP_AGENT_PHONE or "+54 9 343 572-0312",
        "alert_phone": settings.WHATSAPP_ALERT_PHONE or "+54 9 343 453-6447",
        "ai_engine": "Gemini Flash Lite Multimodal",
        "database_backend": "postgresql" if "postgresql" in str(settings.DATABASE_URL) else "sqlite",
        "server_time": datetime.now(timezone.utc).isoformat()
    }

@router.get("/api/v1/dashboard/prospects")
def list_dashboard_prospects(
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Returns prospects with formatted history and last message details."""
    query = db.query(Prospect)

    if status_filter and status_filter != "all":
        query = query.filter(Prospect.status == status_filter)

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (Prospect.name.ilike(search_pattern)) |
            (Prospect.phone.ilike(search_pattern)) |
            (Prospect.contact_name.ilike(search_pattern)) |
            (Prospect.city.ilike(search_pattern))
        )

    prospects = query.order_by(Prospect.updated_at.desc()).all()

    results = []
    for p in prospects:
        try:
            history = json.loads(p.conversation_history or "[]")
        except Exception:
            history = []

        last_msg = history[-1] if history else None
        last_message_text = ""
        last_message_sender = ""
        last_message_time = None
        if last_msg:
            last_message_text = last_msg.get("text", "")
            last_message_sender = last_msg.get("sender", "")
            last_message_time = last_msg.get("timestamp")

        results.append({
            "id": p.id,
            "name": p.name,
            "contact_name": p.contact_name,
            "phone": p.phone,
            "city": p.city or "Entre Ríos",
            "business_type": p.business_type or "General",
            "campaign": p.campaign,
            "status": p.status,
            "meeting_details": p.meeting_details,
            "meeting_scheduled_at": p.meeting_scheduled_at.isoformat() if p.meeting_scheduled_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            "messages_count": len(history),
            "last_message": {
                "text": last_message_text,
                "sender": last_message_sender,
                "timestamp": last_message_time
            },
            "conversation_history": history
        })

    return results

@router.post("/api/v1/dashboard/prospects/{prospect_id}/toggle-takeover")
def toggle_human_takeover(prospect_id: int, db: Session = Depends(get_db)):
    """Toggles human takeover mode to pause or reactivate Sofia on this chat."""
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospecto no encontrado")

    if prospect.status == "human_takeover":
        prospect.status = "in_conversation"
        new_state = "in_conversation"
        msg = f"Sofía reactivada para {prospect.name}."
    else:
        prospect.status = "human_takeover"
        new_state = "human_takeover"
        msg = f"Control manual activado. Sofía en silencio para {prospect.name}."

    prospect.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "status": "success",
        "prospect_id": prospect.id,
        "new_status": new_state,
        "message": msg
    }

@router.post("/api/v1/dashboard/prospects/{prospect_id}/send-message")
async def send_manual_message_from_dashboard(
    prospect_id: int,
    payload: ManualMessagePayload,
    db: Session = Depends(get_db)
):
    """
    Sends a manual WhatsApp message directly to the prospect via Whapi.
    Automatically flags the lead in human_takeover to avoid AI interference.
    """
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospecto no encontrado")

    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")

    # Send via WhatsApp gateway
    sent = await whatsapp.send_whatsapp_message(to_phone=prospect.phone, text=text)

    # Append to conversation history
    try:
        history = json.loads(prospect.conversation_history or "[]")
    except Exception:
        history = []

    history.append({
        "sender": "javier_human",
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    prospect.conversation_history = json.dumps(history, ensure_ascii=False)
    prospect.status = "human_takeover"
    prospect.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "status": "success",
        "message_sent": sent,
        "prospect_id": prospect.id,
        "human_takeover": True
    }

@router.delete("/api/v1/dashboard/prospects/{prospect_id}")
def delete_prospect(prospect_id: int, db: Session = Depends(get_db)):
    """Deletes a prospect record from the database."""
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospecto no encontrado")

    db.delete(prospect)
    db.commit()

    return {"status": "success", "message": f"Prospecto {prospect_id} eliminado."}

@router.post("/api/v1/dashboard/prospects/bulk-import")
async def bulk_import_prospects(
    payload: BulkImportRequest,
    db: Session = Depends(get_db)
):
    """Imports multiple prospects at once and optionally triggers initial outreach."""
    created_count = 0
    updated_count = 0

    for lead in payload.leads:
        clean_phone = "".join(filter(str.isdigit, lead.phone))
        if not clean_phone:
            continue

        existing = db.query(Prospect).filter(Prospect.phone == clean_phone).first()
        if existing:
            existing.name = lead.name or existing.name
            existing.contact_name = lead.contact_name or existing.contact_name
            existing.city = lead.city or existing.city
            existing.business_type = lead.business_type or existing.business_type
            updated_count += 1
        else:
            new_p = Prospect(
                phone=clean_phone,
                name=lead.name,
                contact_name=lead.contact_name,
                city=lead.city or "Paraná",
                business_type=lead.business_type or "General",
                campaign="ai_agency",
                status="pending",
                conversation_history="[]"
            )
            db.add(new_p)
            created_count += 1

    db.commit()

    return {
        "status": "success",
        "created": created_count,
        "updated": updated_count,
        "total": len(payload.leads)
    }

@router.post("/api/v1/dashboard/run-followups")
async def trigger_followups(dry_run: bool = False, db: Session = Depends(get_db)):
    """
    Executes automated follow-up sequence for leads that have not replied.
    """
    from app.services.followup import check_and_send_followups
    return await check_and_send_followups(db, dry_run=dry_run)
