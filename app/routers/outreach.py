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

    # Natural Argentine initial pitch based on campaign
    greeting = f"¡Hola {payload.contact_name}! ¿Cómo estás?" if payload.contact_name else "¡Hola! ¿Cómo estás?"
    referencia = f" Te escribo por {payload.name}." if payload.name and not payload.contact_name else ""

    if campaign == "ai_agency":
        initial_pitch = (
            f"{greeting} Te escribe Sofía.\n\n"
            f"Te cuento algo que te va a llamar la atención: este mensaje que estás leyendo te lo envié de forma 100% autónoma como agente comercial con Inteligencia Artificial.\n\n"
            f"No soy un bot de respuestas automáticas de WhatsApp. Funciono como una ejecutiva comercial digital: busco comercios y clientes potenciales en Google Maps y les escribo en automático entre 12 y 15 por día para abrirte cuentas nuevas que hoy no te compran.\n\n"
            f"Además:\n"
            f"📄 Envío tu catálogo o lista de precios en PDF al instante cuando un cliente me lo pide (24/7, incluso domingos y feriados).\n"
            f"🎙️ Respondo dudas de precios y stock, entendiendo tanto mensajes de texto como notas de voz.\n"
            f"🔔 Apenas detecto un cliente interesado o un pedido, te envío una alerta automática a tu celular personal o a la persona encargada de ventas con los datos listos para facturar o cerrar la venta.\n\n"
            f"Básicamente te traigo clientes nuevos todos los días y le saco el trabajo pesado a tus ventas.\n\n"
            f"¿Te parece que coordinemos una charla breve con un asesor para mostrarte cómo funcionaría con tus productos? La reunión puede ser presencial o virtual.\n\n"
            f"Quedo a disposición.\n\n"
            f"Sofía"
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
