import json
import logging
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.tenant import Tenant, TenantSession, Appointment, MembershipPayment
from app.services import whatsapp
from app.config.settings import settings

logger = logging.getLogger(__name__)

def utc_now():
    return datetime.now(timezone.utc)

class TenantService:
    """
    Enterprise Multi-Tenant Routing & Orchestration Engine:
    Resolves which business (Tenant) is interacting with an incoming WhatsApp message,
    manages brand headers, session state, and tenant knowledge bases.
    """

    @staticmethod
    def get_tenant_by_slug(db: Session, slug: str) -> Optional[Tenant]:
        return db.query(Tenant).filter(Tenant.slug == slug.lower().strip(), Tenant.active == True).first()

    @staticmethod
    def get_tenant_by_keyword(db: Session, keyword: str) -> Optional[Tenant]:
        clean_kw = keyword.lower().strip()
        return db.query(Tenant).filter(Tenant.deep_link_keyword.ilike(f"%{clean_kw}%"), Tenant.active == True).first()

    @staticmethod
    def resolve_incoming_tenant(db: Session, phone: str, message_text: str) -> Tuple[Optional[Tenant], str]:
        """
        Determines the relevant Tenant for an incoming WhatsApp message:
        1. Checks for deep-link keywords (e.g. 'Turno_Clinica_Alvear' or 'Info_Iron_Gym' or '#clinica_alvear').
        2. Checks if the sender has an active session in TenantSession.
        3. Checks if the sender's phone is a registered patient in Appointments or member in Memberships.
        4. Returns (Tenant, cleaned_message_text).
        """
        clean_phone = "".join(filter(str.isdigit, phone))
        msg_upper = message_text.strip().upper()
        msg_lower = message_text.strip().lower()

        # 1. Check explicit hashtags or deep link keywords
        all_tenants = db.query(Tenant).filter(Tenant.active == True).all()
        for t in all_tenants:
            if t.deep_link_keyword and t.deep_link_keyword.upper() in msg_upper:
                # Update or create session
                TenantService.set_active_session(db, clean_phone, t.slug)
                return t, message_text
            if f"#{t.slug.lower()}" in msg_lower or f"#{t.slug.upper()}" in msg_upper:
                TenantService.set_active_session(db, clean_phone, t.slug)
                return t, message_text

        # 2. Check active session (persisted within last 48 hours)
        session = db.query(TenantSession).filter(TenantSession.phone == clean_phone).first()
        if session:
            t = TenantService.get_tenant_by_slug(db, session.tenant_slug)
            if t:
                session.last_interaction = utc_now()
                db.commit()
                return t, message_text

        # 3. Check if phone is an existing patient or member
        recent_apt = db.query(Appointment).filter(Appointment.patient_phone == clean_phone).order_by(Appointment.id.desc()).first()
        if recent_apt and recent_apt.tenant:
            TenantService.set_active_session(db, clean_phone, recent_apt.tenant.slug)
            return recent_apt.tenant, message_text

        recent_mem = db.query(MembershipPayment).filter(MembershipPayment.member_phone == clean_phone).order_by(MembershipPayment.id.desc()).first()
        if recent_mem and recent_mem.tenant:
            TenantService.set_active_session(db, clean_phone, recent_mem.tenant.slug)
            return recent_mem.tenant, message_text

        # No tenant matched
        return None, message_text

    @staticmethod
    def set_active_session(db: Session, phone: str, tenant_slug: str, context: Optional[dict] = None) -> TenantSession:
        clean_phone = "".join(filter(str.isdigit, phone))
        session = db.query(TenantSession).filter(TenantSession.phone == clean_phone).first()
        if not session:
            session = TenantSession(
                phone=clean_phone,
                tenant_slug=tenant_slug,
                context_data=json.dumps(context or {}),
                last_interaction=utc_now()
            )
            db.add(session)
        else:
            session.tenant_slug = tenant_slug
            if context:
                session.context_data = json.dumps(context)
            session.last_interaction = utc_now()
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def format_branded_message(tenant: Tenant, body_text: str) -> str:
        """
        Prepends the Tenant's official branding header to the message body.
        Ensures consistent corporate presence without confusing the recipient.
        """
        header = tenant.branding_header or f"🏢 *{tenant.name.upper()}*\n_Asistente y Notificaciones Oficiales_\n"
        return f"{header.strip()}\n\n{body_text.strip()}"

    @staticmethod
    async def send_branded_notification(
        tenant: Tenant,
        to_phone: str,
        body_text: str,
        with_logo: bool = False
    ) -> bool:
        """
        Dispatches a branded WhatsApp message with the Tenant's brand header and optional HD logo.
        """
        full_text = TenantService.format_branded_message(tenant, body_text)
        if with_logo and tenant.logo_url:
            return await whatsapp.send_whatsapp_image(to_phone, tenant.logo_url, caption=full_text)
        return await whatsapp.send_whatsapp_message(to_phone, full_text)

    @staticmethod
    def build_tenant_system_prompt(tenant: Tenant) -> str:
        """
        Dynamically constructs Gemini's system prompt by injecting the Tenant's knowledge base,
        active modules, tone, and operational boundaries.
        """
        kb_text = tenant.knowledge_base or "{}"
        try:
            kb_obj = json.loads(kb_text)
            kb_formatted = json.dumps(kb_obj, indent=2, ensure_ascii=False)
        except Exception:
            kb_formatted = kb_text

        prompt = f"""
Sos Sofía, la secretaria ejecutiva y asistente oficial de '{tenant.name}'.
Rubro del negocio: {tenant.business_type.upper()}.
Módulos habilitados: {tenant.modules_enabled}.

PAUTAS DE COMUNICACIÓN Y TONO:
- Sé extremadamente amable, cálida, ejecutiva y profesional.
- Hablá en español rioplatense educado y claro (tuteo respetuoso o de confianza según el rubro).
- Nunca digas que sos un bot genérico ni menciones otras empresas o clientes.
- Siempre representás exclusivamente a '{tenant.name}'.

BASE DE CONOCIMIENTO OFICIAL DEL COMERCIO/CLÍNICA:
\"\"\"
{kb_formatted}
\"\"\"

REGLAS DE OPERACIÓN:
1. Respondé dudas sobre horarios, precios, especialidades, ubicación y formas de pago basándote ESTRICTAMENTE en la base de conocimiento arriba.
2. Si te preguntan algo que no figura en la base de conocimiento, no inventes: deciles que vas a consultar con la administración y que te dejen su consulta.
3. Si el usuario desea agendar, cancelar o confirmar un turno, guialo con empatía.
4. Si el usuario envía una foto o comprobante de transferencia, confirmale la recepción amablemente.
5. Mantené las respuestas concisas (ideales para leer rápido en WhatsApp).
"""
        return prompt.strip()

tenant_service = TenantService()
