import json
import logging
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.tenant import Tenant, TenantSession, Appointment, MembershipPayment, WaitlistEntry
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

        # Phone candidate variants (with/without country/mobile prefix '9')
        cand_phones = [clean_phone]
        if clean_phone.startswith("549"):
            cand_phones.append("54" + clean_phone[3:])
        elif clean_phone.startswith("54") and not clean_phone.startswith("549"):
            cand_phones.append("549" + clean_phone[2:])

        # 2. Priority check: if phone has an active waitlist offer ('notificado_oferta'), route to that clinic!
        active_wl_offer = db.query(WaitlistEntry).filter(
            WaitlistEntry.patient_phone.in_(cand_phones),
            WaitlistEntry.status == "notificado_oferta"
        ).order_by(WaitlistEntry.id.desc()).first()
        if active_wl_offer and active_wl_offer.tenant and active_wl_offer.tenant.active:
            TenantService.set_active_session(db, clean_phone, active_wl_offer.tenant.slug)
            return active_wl_offer.tenant, message_text

        # 3. Check active session (persisted within last 48 hours)
        session = db.query(TenantSession).filter(TenantSession.phone == clean_phone).first()
        if session:
            t = TenantService.get_tenant_by_slug(db, session.tenant_slug)
            if t:
                session.last_interaction = utc_now()
                db.commit()
                return t, message_text

        # 4. Check if phone is an existing patient, waitlist candidate, or member
        recent_apt = db.query(Appointment).filter(Appointment.patient_phone.in_(cand_phones)).order_by(Appointment.id.desc()).first()
        if recent_apt and recent_apt.tenant and recent_apt.tenant.active:
            TenantService.set_active_session(db, clean_phone, recent_apt.tenant.slug)
            return recent_apt.tenant, message_text

        recent_wl = db.query(WaitlistEntry).filter(WaitlistEntry.patient_phone.in_(cand_phones)).order_by(WaitlistEntry.id.desc()).first()
        if recent_wl and recent_wl.tenant and recent_wl.tenant.active:
            TenantService.set_active_session(db, clean_phone, recent_wl.tenant.slug)
            return recent_wl.tenant, message_text

        # Check if phone is owner/doctor of a tenant
        owner_tenant = db.query(Tenant).filter(Tenant.owner_phone.in_(cand_phones), Tenant.active == True).order_by(Tenant.id.asc()).first()
        if owner_tenant:
            TenantService.set_active_session(db, clean_phone, owner_tenant.slug)
            return owner_tenant, message_text

        recent_mem = db.query(MembershipPayment).filter(MembershipPayment.member_phone.in_(cand_phones)).order_by(MembershipPayment.id.desc()).first()
        if recent_mem and recent_mem.tenant and recent_mem.tenant.active:
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

        turnos_protocol = ""
        if "turnos_rellena_huecos" in tenant.modules_enabled or tenant.business_type in ["salud", "medicina", "estetica"]:
            turnos_protocol = """
PROTOCOLO CLÍNICO DE AGENDAMIENTO AUTÓNOMO:
- Si el paciente solicita un turno ('quiero turno', 'tenés turno para hoy a las 17', 'necesito turno', 'agendame'):
  1. Si indica su nombre (o ya lo conocés) y el día/horario que desea (o acepta uno sugerido):
     Confirmale el turno con calidez rioplatense, indicando fecha, hora y el nombre del profesional.
     Y al FINAL de tu respuesta, en una línea separada, agregá EXACTAMENTE:
     [AGENDAR_TURNO: {"paciente": "Nombre del Paciente", "fecha_hora": "YYYY-MM-DDTHH:MM:00", "servicio": "Profesional o Especialidad"}]
     (Usá la fecha actual de referencia para calcular el ISO YYYY-MM-DDTHH:MM:00).
  2. Si no indicó su nombre o el horario exacto, pedíselo amablemente para poder agendarlo.
- Si el paciente indica que no podrá asistir o pide cancelar su turno:
  Confirmale que procedés a cancelar su turno para que no se preocupe y agrega al final:
  [CANCEL_APPOINTMENT_INTENT]
"""

        now_ref = utc_now().strftime("%A %d de %B de %Y, %H:%M hs (UTC)")

        prompt = f"""
Sos Sofía, la secretaria ejecutiva y asistente oficial de '{tenant.name}'.
Rubro del negocio: {tenant.business_type.upper()}.
Módulos habilitados: {tenant.modules_enabled}.
Fecha actual de referencia: {now_ref}.

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
3. Si el usuario desea agendar, cancelar o confirmar un turno, guialo con empatía.{turnos_protocol}
4. Si el usuario envía una foto o comprobante de transferencia, confirmale la recepción amablemente.
5. Mantené las respuestas concisas (ideales para leer rápido en WhatsApp).
"""
        return prompt.strip()

    @staticmethod
    async def setup_doctor_live_demo(
        db: Session,
        doctor_name: str,
        doctor_phone: str,
        clinic_name: str = "Consultorios Médicos San Martín (Demo)",
        boss_phone: Optional[str] = None,
        secondary_phone: Optional[str] = None,
        slug: str = "demo_consultorio",
        send_welcome_whatsapp: bool = True
    ) -> Dict[str, Any]:
        """
        Activates or reconfigures a live clinical demo on-the-fly from WhatsApp (Modo Jefe) or CLI:
        1. Updates or creates the demo tenant with the doctor's name, clinic name, and phone.
        2. Clears past demo appointments and waitlist entries for a 100% clean slate.
        3. Pre-registers Javier's personal phone in the waitlist as 'Laura Benítez' (activa).
        4. Binds the secondary phone session directly to this clinic tenant.
        5. Sends an official welcome WhatsApp alert to the doctor's real phone.
        """
        from app.services.boss_mode import normalize_argentine_phone

        clean_doc_phone = "".join(filter(str.isdigit, doctor_phone))
        norm_doc_phone = normalize_argentine_phone(clean_doc_phone)

        # Normalize boss and secondary phones
        default_boss = "".join(filter(str.isdigit, str(settings.WHATSAPP_ALERT_PHONE or "5493434536447")))
        actual_boss = "".join(filter(str.isdigit, boss_phone)) if boss_phone else default_boss
        actual_sec = "".join(filter(str.isdigit, secondary_phone)) if secondary_phone else "5493435730520"

        # Format doctor title nicely if needed
        clean_doc_name = doctor_name.strip()
        if not any(clean_doc_name.lower().startswith(p) for p in ["dr.", "dr ", "dra.", "dra ", "doctor", "doctora"]):
            clean_doc_name = f"Dr. {clean_doc_name}"

        # 1. Get or create Tenant
        tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
        if not tenant:
            tenant = Tenant(
                slug=slug,
                name=clinic_name,
                business_type="salud",
                owner_name=clean_doc_name,
                owner_phone=norm_doc_phone,
                branding_header=f"🏥 *{clinic_name}*",
                modules_enabled='["turnos_rellena_huecos", "recordatorios", "faq"]',
                knowledge_base=json.dumps({
                    "especialidad": "Medicina General y Odontología",
                    "horarios": "Lunes a Viernes 08:00 a 20:00 hs",
                    "profesional": clean_doc_name
                }, ensure_ascii=False),
                active=True
            )
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
        else:
            tenant.name = clinic_name
            tenant.owner_name = clean_doc_name
            tenant.owner_phone = norm_doc_phone
            tenant.branding_header = f"🏥 *{clinic_name}*"
            tenant.active = True
            tenant.knowledge_base = json.dumps({
                "especialidad": "Medicina General y Odontología",
                "horarios": "Lunes a Viernes 08:00 a 20:00 hs",
                "profesional": clean_doc_name
            }, ensure_ascii=False)
            db.commit()
            db.refresh(tenant)

        # 2. Clean past appointments & waitlist
        db.query(Appointment).filter(Appointment.tenant_id == tenant.id).delete()
        db.query(WaitlistEntry).filter(WaitlistEntry.tenant_id == tenant.id).delete()
        db.commit()

        # 3. Pre-register Javier's personal phone in waitlist as Laura Benítez
        wl_entry = WaitlistEntry(
            tenant_id=tenant.id,
            patient_name="Laura Benítez",
            patient_phone=actual_boss,
            doctor_or_service=f"{clean_doc_name} - Odontología",
            preferred_time_range="Por la tarde",
            status="activa"
        )
        db.add(wl_entry)
        db.commit()
        db.refresh(wl_entry)

        # 4. Pre-bind active session for doctor, secondary phone and boss phone
        TenantService.set_active_session(db, norm_doc_phone, tenant.slug)
        TenantService.set_active_session(db, actual_sec, tenant.slug)
        TenantService.set_active_session(db, actual_boss, tenant.slug)

        # 5. Send Welcome WhatsApp Message to the Doctor
        if send_welcome_whatsapp and norm_doc_phone:
            welcome_text = (
                f"🏥 *{clinic_name}*\n\n"
                f"¡Hola *{clean_doc_name}*! Te damos la bienvenida a *Sofía AI*.\n\n"
                f"A partir de este momento, este celular queda conectado como la *línea ejecutiva* de tu consultorio.\n\n"
                f"Vas a recibir acá en tiempo real las notificaciones de nuevos turnos agendados, cancelaciones imprevistas y vacantes recuperadas automáticamente."
            )
            try:
                # 1. Attempt sending official Meta Utility Template (bypasses 24h window)
                sent_template = await whatsapp.send_whatsapp_template(
                    to_phone=norm_doc_phone,
                    template_name="activacion_linea_ejecutiva_v1",
                    language_code="es_AR",
                    body_params=[clean_doc_name, clinic_name]
                )
                if not sent_template:
                    # 2. Fallback to direct text (works if 24h window is open or in simulation)
                    await whatsapp.send_whatsapp_message(to_phone=norm_doc_phone, text=welcome_text)
                logger.info(f"📲 Sent welcome WhatsApp alert to Doctor {clean_doc_name} (+{norm_doc_phone}) (template={sent_template})")
            except Exception as e:
                logger.error(f"Error sending welcome WhatsApp to doctor: {e}")

        return {
            "status": "success",
            "tenant_id": tenant.id,
            "tenant_slug": tenant.slug,
            "clinic_name": clinic_name,
            "doctor_name": clean_doc_name,
            "doctor_phone": norm_doc_phone,
            "waitlist_phone": actual_boss,
            "waitlist_id": wl_entry.id,
            "patient_phone": actual_sec
        }

tenant_service = TenantService()
