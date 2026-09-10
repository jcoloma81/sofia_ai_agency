import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.prospect import Prospect
from app.services import whatsapp
from app.config.settings import settings
from prospector.scraper import clean_phone_number

logger = logging.getLogger(__name__)

router = APIRouter()

class OutreachRequest(BaseModel):
    phone: str
    name: str
    contact_name: Optional[str] = None
    city: Optional[str] = None
    units_count: Optional[int] = None
    campaign: Optional[str] = "ai_agency"
    business_type: Optional[str] = None
    strategy: Optional[str] = "two_step"

class BatchOutreachRequest(BaseModel):
    leads: List[OutreachRequest]
    delay_seconds: Optional[int] = 5

from pydantic import BaseModel, ConfigDict

class ProspectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    contact_name: Optional[str] = None
    phone: str
    city: Optional[str] = None
    units_count: Optional[int] = None
    campaign: Optional[str] = "ai_agency"
    business_type: Optional[str] = None
    status: str
    meeting_details: Optional[str] = None
    created_at: datetime
    updated_at: datetime

@router.post("/start-outreach")
async def start_outreach(
    payload: OutreachRequest,
    db: Session = Depends(get_db)
):
    """
    Initiates B2B outbound conversation with a new prospect by sending an introductory consultative pitch.
    """
    clean_phone = clean_phone_number(payload.phone) or "".join(filter(str.isdigit, payload.phone))
    prospect = db.query(Prospect).filter(Prospect.phone == clean_phone).first()

    if prospect and prospect.status == "unsubscribed":
        return {
            "status": "skipped",
            "reason": "Prospect requested opt-out (unsubscribed)",
            "phone": clean_phone
        }

    campaign = payload.campaign or "ai_agency"
    business_type = payload.business_type

    if not prospect:
        prospect = Prospect(
            phone=clean_phone,
            name=payload.name,
            contact_name=payload.contact_name,
            city=payload.city or "Entre Ríos / Santa Fe",
            units_count=payload.units_count,
            campaign=campaign,
            business_type=business_type,
            status="contacted",
            conversation_history="[]"
        )
        db.add(prospect)
    else:
        prospect.name = payload.name
        prospect.contact_name = payload.contact_name or prospect.contact_name
        prospect.city = payload.city or prospect.city
        prospect.campaign = campaign
        if business_type:
            prospect.business_type = business_type
        prospect.status = "contacted"
        prospect.meeting_details = None
        prospect.meeting_scheduled_at = None

    # Determine pitch & template strategy
    if getattr(payload, "strategy", "two_step") == "direct_pitch" and campaign in ["ai_agency", "canchas_futbol"]:
        clean_company = payload.name.strip() if payload.name else "tu negocio"
        initial_pitch = (
            "Hola! Mi nombre es SOFÍA. Así como te contacté a vos, puedo hacer lo mismo para captar clientes nuevos para tu negocio o atender las 24 hs a los que ya tenés.\n\n"
            "Mi función es sacar el trabajo repetitivo que quita tiempo en WhatsApp:\n"
            "• Respondo consultas al instante, paso listas de precios, presupuestos o disponibilidad de turnos.\n"
            "• Registro pedidos o reservas de manera autónoma y le derivo la confirmación por WhatsApp a la persona encargada en tu empresa.\n"
            "• Busco clientes nuevos (vos podés estar descansando y yo generando oportunidades de manera autónoma con el nombre de tu negocio).\n\n"
            "Si te interesa la propuesta, un asesor se puede comunicar con ustedes para coordinar una reunión breve (virtual o presencial).\n\n"
            "Quedo a disposición.\nSOFÍA - ASISTENTE VIRTUAL"
        )
        components = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": clean_company}
                ]
            }
        ]
        template_chain = ["pitch_directo_v1", "pitch_universal_v1", "contacto_comercial_v3", "contacto_comercial_v1"]
    elif campaign in ["ai_agency", "canchas_futbol"]:
        clean_company = payload.name.strip() if payload.name else ("el complejo" if campaign == "canchas_futbol" else "la empresa")
        initial_pitch = f"Hola buenas! Te escribo por {clean_company}, este es su WhatsApp?"
        components = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": clean_company}
                ]
            }
        ]
        template_chain = ["contacto_comercial_v3", "contacto_comercial_v2", "contacto_comercial_v1"]
    else:
        initial_pitch = (
            f"{greeting} Te escribe Sofía de Air Control.\n\n"
            f"Somos una empresa nueva y estamos ofreciendo un sistema para el ahorro energético enfocado en hoteles y alojamientos turísticos.\n\n"
            f"El sistema permite reducir la factura eléctrica hasta en un 50% o más, dependiendo de la configuración. La instalación es rápida, limpia, pero lo más importante: ¡funciona muy bien!\n\n"
            f"Lo que proponemos con este mensaje es coordinar una reunión breve (presencial o virtual) para que nuestro asesor les muestre en detalle el funcionamiento.\n\n"
            f"¿Les parece que coordinemos unos minutos? Quedo a disposición.\n\n"
            f"Sofía — Air Control"
        )
        components = None
        template_chain = []

    history = [{
        "sender": "ai",
        "text": initial_pitch,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }]
    prospect.conversation_history = json.dumps(history, ensure_ascii=False)
    db.commit()
    db.refresh(prospect)

    sent = False
    if campaign in ["ai_agency", "canchas_futbol"] and settings.META_ACCESS_TOKEN:
        for t_name in template_chain:
            curr_components = None if t_name == "pitch_directo_v1" else components
            sent = await whatsapp.send_whatsapp_template(
                to_phone=clean_phone,
                template_name=t_name,
                language_code="es_AR",
                components=curr_components
            )
            if sent:
                break
        if not sent:
            sent = await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=initial_pitch)
    else:
        sent = await whatsapp.send_whatsapp_message(to_phone=clean_phone, text=initial_pitch)

    return {
        "status": "outreach_started",
        "prospect_id": prospect.id,
        "phone": clean_phone,
        "campaign": campaign,
        "message_sent": sent
    }

@router.post("/start-batch-outreach")
async def start_batch_outreach(
    payload: BatchOutreachRequest,
    db: Session = Depends(get_db)
):
    """
    Initiates outreach to multiple prospects sequentially.
    """
    results = []
    for lead in payload.leads:
        try:
            res = await start_outreach(lead, db)
            results.append(res)
        except Exception as err:
            logger.error(f"Error starting outreach for {lead.phone}: {err}")
            results.append({"phone": lead.phone, "status": "error", "error": str(err)})
    return {
        "status": "batch_completed",
        "total": len(results),
        "results": results
    }

@router.get("/prospects", response_model=List[ProspectResponse])
def list_prospects(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    campaign_filter: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Returns list of prospects and their current outreach status.
    """
    query = db.query(Prospect)
    if status_filter:
        query = query.filter(Prospect.status == status_filter)
    if campaign_filter:
        query = query.filter(Prospect.campaign == campaign_filter)
    return query.order_by(Prospect.updated_at.desc()).offset(skip).limit(limit).all()

@router.get("/status")
def get_sdr_status(db: Session = Depends(get_db)):
    """
    Returns summary metrics of the autonomous SDR assistant.
    """
    total = db.query(Prospect).count()
    meetings = db.query(Prospect).filter(Prospect.status == "meeting_scheduled").count()
    in_chat = db.query(Prospect).filter(Prospect.status == "in_conversation").count()
    air_control_count = db.query(Prospect).filter(Prospect.campaign == "air_control").count()
    ai_agency_count = db.query(Prospect).filter(Prospect.campaign == "ai_agency").count()

    return {
        "status": "active",
        "agent_name": "Sofía (Sofía AI Agency B2B SDR)",
        "agent_phone": "+54 9 343 572-0312",
        "alert_phone": "+54 9 343 453-6447",
        "total_prospects": total,
        "active_conversations": in_chat,
        "meetings_scheduled": meetings,
        "campaigns": {
            "ai_agency": ai_agency_count,
            "air_control": air_control_count
        }
    }
