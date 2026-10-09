import os
import re
import json
import time
import asyncio
import logging
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.config.settings import settings
from app.models.tenant import Tenant
from app.models.prospect import Prospect
from app.services import whatsapp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding", tags=["Client Digital Onboarding"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", "uploads", "onboarding")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv", ".jpg", ".jpeg", ".png", ".doc", ".docx"}

def generate_safe_slug(business_name: str, db: Session) -> str:
    """Generates a URL and code-safe unique slug for a new tenant."""
    normalized = unicodedata.normalize('NFKD', business_name).encode('ASCII', 'ignore').decode('utf-8')
    base = re.sub(r"[^a-z0-9]+", "_", normalized.lower().strip()).strip("_")
    if not base:
        base = "negocio"
    
    slug = base
    counter = 1
    while db.query(Tenant).filter(Tenant.slug == slug).first():
        slug = f"{base}_{counter}"
        counter += 1
    return slug

def sanitize_phone(raw_phone: str) -> str:
    """Normalizes phone to digits-only E.164 without symbols."""
    digits = "".join(filter(str.isdigit, str(raw_phone or "")))
    if digits.startswith("0"):
        digits = digits[1:]
    if digits.startswith("15") and len(digits) >= 10:
        digits = digits[2:]
    if not digits.startswith("54"):
        digits = f"549{digits}"
    elif digits.startswith("54") and not digits.startswith("549"):
        digits = f"549{digits[2:]}"
    return digits

@router.post("/submit")
async def submit_client_onboarding(
    business_name: str = Form(...),
    business_type: str = Form(...),
    owner_name: str = Form(...),
    owner_phone: str = Form(...),
    owner_email: Optional[str] = Form(None),
    city: str = Form("Paraná"),
    operating_hours: str = Form(...),
    appointment_duration: Optional[str] = Form("30 min"),
    requires_deposit: Optional[str] = Form("no"),
    deposit_amount: Optional[str] = Form(None),
    emergency_contact: Optional[str] = Form(None),
    price_notes: Optional[str] = Form(None),
    line_type: Optional[str] = Form("shared"),
    dedicated_phone: Optional[str] = Form(None),
    agenda_status: Optional[str] = Form("libre"),
    catalog_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """
    Submits client operational onboarding data, saves tenant record,
    stores attached price lists / appointment agendas (PDF/Excel/photo),
    and notifies Javier Coloma via WhatsApp.
    """
    clean_name = business_name.strip()
    clean_owner = owner_name.strip()
    clean_phone = sanitize_phone(owner_phone)
    clean_type = business_type.lower().strip()
    clean_email = (owner_email or "").strip().lower() or None
    
    if not clean_name or not clean_owner or not clean_phone:
        raise HTTPException(status_code=400, detail="Nombre del negocio, titular y teléfono de WhatsApp son obligatorios.")

    # 1. Handle File Upload if provided (price list, agenda photo, etc.)
    saved_file_rel = None
    original_filename = None
    if catalog_file and catalog_file.filename:
        original_filename = catalog_file.filename
        _, ext = os.path.splitext(original_filename.lower())
        if ext in ALLOWED_EXTENSIONS:
            safe_fname = f"onboarding_{int(time.time())}_{re.sub(r'[^a-zA-Z0-9_.-]', '_', original_filename)}"
            file_path = os.path.join(UPLOAD_DIR, safe_fname)
            try:
                content = await catalog_file.read()
                with open(file_path, "wb") as f:
                    f.write(content)
                saved_file_rel = f"/assets/uploads/onboarding/{safe_fname}"
                logger.info(f"📁 Onboarding file saved: {file_path} ({len(content)} bytes)")
            except Exception as e:
                logger.error(f"Error saving onboarding file: {e}")
        else:
            logger.warning(f"File extension {ext} not in allowed list for onboarding.")

    # 2. Determine line mode (shared vs dedicated)
    is_dedicated = (line_type or "").lower().strip() in ["dedicated", "propia", "linea_propia", "linea propia"]
    clean_dedicated = sanitize_phone(dedicated_phone) if dedicated_phone and dedicated_phone.strip() else None

    # 3. Generate unique slug and knowledge base
    slug = generate_safe_slug(clean_name, db)
    
    requires_dep_bool = requires_deposit.lower() in ["si", "sí", "true", "yes", "1"]
    kb_data = {
        "business_name": clean_name,
        "business_type": clean_type,
        "owner_name": clean_owner,
        "owner_phone": clean_phone,
        "owner_email": clean_email,
        "city": city.strip(),
        "line_type": "dedicated" if is_dedicated else "shared",
        "dedicated_phone": clean_dedicated,
        "agenda_status": (agenda_status or "libre").strip(),
        "operating_hours": operating_hours.strip(),
        "appointment_duration": appointment_duration or "30 min",
        "requires_deposit": requires_dep_bool,
        "deposit_amount": deposit_amount.strip() if deposit_amount else None,
        "emergency_contact": emergency_contact.strip() if emergency_contact else None,
        "price_notes": price_notes.strip() if price_notes else None,
        "catalog_file_url": saved_file_rel,
        "catalog_file_name": original_filename,
        "submitted_at": datetime.now(timezone.utc).isoformat()
    }

    # 4. Create or update Tenant record with strict data isolation
    modules = ["turnos_rellena_huecos", "recordatorios", "faq"]
    if clean_type in ["gym", "gimnasio"]:
        modules.append("cobranzas_mp")

    tenant = Tenant(
        slug=slug,
        name=clean_name,
        business_type=clean_type,
        owner_phone=clean_phone,
        owner_name=clean_owner,
        owner_email=clean_email,
        deep_link_keyword=slug.capitalize(),
        modules_enabled=json.dumps(modules),
        knowledge_base=json.dumps(kb_data, ensure_ascii=False),
        plan_type="dedicated" if is_dedicated else "shared",
        monthly_message_quota=99999 if is_dedicated else 150,
        active=True
    )
    db.add(tenant)

    # 4. Update or link Prospect in CRM
    prospect = db.query(Prospect).filter(Prospect.phone == clean_phone).first()
    if prospect:
        prospect.name = clean_name
        prospect.contact_name = clean_owner
        prospect.city = city.strip()
        prospect.campaign = "client_onboarding"
        prospect.status = "onboarded"
        prospect.notes = f"Tenant ID: {slug} | Alta Digital completada"
    else:
        new_pros = Prospect(
            phone=clean_phone,
            name=clean_name,
            contact_name=clean_owner,
            city=city.strip(),
            campaign="client_onboarding",
            status="onboarded",
            notes=f"Tenant ID: {slug} | Alta Digital completada"
        )
        db.add(new_pros)

    db.commit()
    db.refresh(tenant)

    # 5. Dispatch WhatsApp Alert to Javier Coloma
    boss_phone = "".join(filter(str.isdigit, str(settings.WHATSAPP_ALERT_PHONE or "5493434536447")))
    rubro_icons = {
        "salud": "🏥",
        "consultorio": "🏥",
        "gym": "🏋️‍♂️",
        "gimnasio": "🏋️‍♂️",
        "veterinaria": "🐾",
        "taller": "🚗",
        "distribuidora": "📦",
        "comercio": "🛍️"
    }
    icon = rubro_icons.get(clean_type, "🏢")
    
    file_info = f"📎 Archivo adjunto: *{original_filename}*" if original_filename else ("📝 Precios cargados por texto" if price_notes else "ℹ️ Sin archivo adjunto")
    deposit_info = f"💰 Seña: ${deposit_amount}" if requires_dep_bool and deposit_amount else ("💰 Seña requerida" if requires_dep_bool else "Pago en el local")
    line_mode_info = f"📲 Línea Propia Exclusiva" + (f" (+{clean_dedicated})" if clean_dedicated else " (chip nuevo a homologar)") if is_dedicated else "🌐 Central Verificada Compartida (Enlace/QR)"
    agenda_info = "📅 Agenda: Libre desde cero" if agenda_status == "libre" else f"📅 Agenda: {agenda_status}"

    alert_text = (
        f"🎉 *[NUEVA ALTA DE CLIENTE ONLINE]* 🚀\n\n"
        f"{icon} *Negocio:* {clean_name} ({clean_type.capitalize()})\n"
        f"👤 *Titular:* {clean_owner}\n"
        f"📱 *WhatsApp Personal Titular:* +{clean_phone}\n"
        f"📧 *E-mail:* {clean_email or 'No especificado'}\n"
        f"📍 *Ciudad:* {city.strip()}\n"
        f"⚙️ *Modalidad Línea:* {line_mode_info}\n"
        f"{agenda_info}\n"
        f"⏰ *Horarios:* {operating_hours.strip()}\n"
        f"⏱️ *Duración turnos:* {appointment_duration or '30 min'}\n"
        f"{file_info}\n"
        f"💵 *Modalidad Cobro:* {deposit_info}\n"
        f"🏷️ *Abono:* $30.000 finales / mes\n\n"
        f"👉 *Acción:* Revisá la ficha en el Dashboard y coordiná la vinculación de la línea."
    )

    if boss_phone:
        asyncio.create_task(whatsapp.send_owner_or_admin_alert(
            to_phone=boss_phone,
            fallback_text=alert_text,
            business_name="Sofía AI Agency",
            event_type="Nueva Alta de Cliente Online",
            client_title=f"{clean_name} ({clean_owner})",
            details_summary=f"Titular: {clean_owner} | Tel: +{clean_phone} | Email: {clean_email or 'N/A'}",
            owner_email=settings.MAIL_USERNAME or settings.MAIL_FROM or "colomajavier@gmail.com"
        ))
        logger.info(f"📲 Multi-channel alert dispatched to boss ({boss_phone}) for new tenant {clean_name} ({slug})")

    # Send client welcome / confirmation email if email is provided
    if clean_email and "@" in clean_email:
        try:
            from app.services.alerts import send_email_alert, build_onboarding_welcome_html_email
            client_welcome_html = build_onboarding_welcome_html_email(
                business_name=clean_name,
                owner_name=clean_owner,
                line_type=line_mode_info,
                operating_hours=operating_hours.strip()
            )
            asyncio.create_task(send_email_alert(
                subject=f"🚀 ¡Bienvenido a Sofía AI Agency! (Alta de {clean_name})",
                recipient=clean_email,
                html_content=client_welcome_html
            ))
            logger.info(f"📧 Confirmation welcome email sent to client {clean_email}")
        except Exception as welcome_err:
            logger.debug(f"Welcome email dispatch failed: {welcome_err}")

    return {
        "status": "success",
        "tenant_id": tenant.id,
        "slug": tenant.slug,
        "business_name": tenant.name,
        "message": f"¡Información de {clean_name} recibida con éxito! Iniciamos la puesta en marcha de Sofía.",
        "plan_amount": 30000,
        "currency": "ARS",
        "file_uploaded": bool(saved_file_rel)
    }

@router.get("/status/{slug}")
def check_onboarding_status(slug: str, db: Session = Depends(get_db)):
    """Checks the onboarding and activation status of a tenant."""
    tenant = db.query(Tenant).filter(Tenant.slug == slug.lower().strip()).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Negocio no encontrado.")
    return {
        "status": "success",
        "tenant_id": tenant.id,
        "slug": tenant.slug,
        "name": tenant.name,
        "business_type": tenant.business_type,
        "active": tenant.active,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None
    }
