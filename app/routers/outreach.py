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
    clean_phone = "".join(filter(str.isdigit, payload.phone))
    prospect = db.query(Prospect).filter(Prospect.phone == clean_phone).first()

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

    # Natural Argentine initial pitch based on campaign
    greeting = f"¡Hola! Te escribo por {payload.name}." if payload.name else "¡Hola!"

    if campaign == "ai_agency":
        initial_pitch = (
            f"{greeting} Te escribe Sofía.\n\n"
            f"Te escribo de forma 100% autónoma. Mi trabajo es encontrar empresas para vender productos o servicios: así como te contacté a vos, puedo buscar clientes y atenderlos bajo el propio logo y marca de tu negocio, 24/7.\n\n"
            f"No soy un bot común de respuestas automáticas de WhatsApp Business. Funciono como una ejecutiva comercial digital que hace el trabajo pesado de tus ventas:\n\n"
            f"🎯 Salgo a buscar clientes: Encuentro comercios en Google Maps y les escribo en automático entre 12 y 15 por día con el logo de tu empresa para abrirte cuentas nuevas.\n"
            f"📄 Atención 24/7: Paso propuestas o tarifarios en PDF y respondo consultas al instante (incluso audios de voz, de noche o feriados).\n"
            f"🔔 Alerta de cierre: Apenas detecto un interesado o un pedido grande, te aviso directo a tu celular para que cierres la venta.\n\n"
            f"¿Te parece que coordinemos una charla breve de 10 minutos con Lucas, nuestro asesor, para mostrarte cómo funcionaría con los servicios de tu empresa? (puede ser presencial si están en la zona o virtual).\n\n"
            f"Quedo a tu disposición.\n\n"
            f"Sofía — Asistente Comercial con IA"
        )
    else:
        initial_pitch = (
            f"{greeting} Te escribe Sofía de Air Control.{referencia}\n\n"
            f"Somos una empresa nueva y estamos ofreciendo un sistema para el ahorro energético enfocado en hoteles y alojamientos turísticos.\n\n"
            f"El sistema permite reducir la factura eléctrica hasta en un 50% o más, dependiendo de la configuración. La instalación es rápida, limpia, pero lo más importante: ¡funciona muy bien!\n\n"
            f"Lo que proponemos con este mensaje es coordinar una reunión breve (presencial o virtual) para que nuestro asesor les muestre en detalle el funcionamiento.\n\n"
            f"¿Les parece que coordinemos unos minutos? Quedo a disposición.\n\n"
            f"Sofía — Air Control"
        )

    history = [{
        "sender": "ai",
        "text": initial_pitch,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }]
    prospect.conversation_history = json.dumps(history, ensure_ascii=False)
    db.commit()
    db.refresh(prospect)

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
