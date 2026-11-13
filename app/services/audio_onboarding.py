import os
import re
import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple

import httpx
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.tenant import Tenant
from app.models.prospect import Prospect
from app.routers.onboarding import generate_safe_slug, sanitize_phone
from app.services import whatsapp

logger = logging.getLogger(__name__)

ONBOARDING_TRIGGERS = [
    "alta", "dar de alta", "activar clinica", "activar clínica",
    "alta clinica", "alta clínica", "alta consultorio",
    "onboarding", "quiero empezar", "activar sofia", "activar sofía",
    "nuevo consultorio", "nueva clinica", "nueva clínica",
    "iniciar alta", "empezar alta", "alta por audio"
]

DEFAULT_PROMPT_STEP_1 = (
    "👋 *¡Hola! Qué gusto saludarte.* Soy Sofía y te voy a acompañar en la activación de tu consultorio en *4 audios cortos de 30 segundos* (o por texto si preferís).\n\n"
    "🎙️ *Audio 1:* **¿Cómo se llama tu clínica o consultorio, en qué ciudad están y cuál es tu nombre completo?**"
)

DEFAULT_PROMPT_STEP_2 = (
    "🎙️ *Audio 2:* **¿Quiénes atienden en la clínica, qué especialidad hace cada profesional y con qué obras sociales o prepagas trabajan (o si atienden solo particular)?**"
)

DEFAULT_PROMPT_STEP_3 = (
    "🎙️ *Audio 3:* **¿Qué días y horarios atiende cada profesional? ¿Y cuánto calculan que dura una consulta promedio (ej: 30 o 45 minutos)?**"
)

DEFAULT_PROMPT_STEP_4 = (
    "🎙️ *Audio 4:* **¿Cuánto cobran la consulta particular básica? ¿Piden seña previa para reservar o pagan en el consultorio? Y si alguien cae con un dolor urgente, ¿cómo querés que proceda Sofía?**"
)


class AudioOnboardingService:
    """
    Motor de Onboarding por Audios de WhatsApp con Gemini Flash Multimodal.
    Permite a un médico o dueño de consultorio completar su relevamiento operativo
    y puesta en marcha sin formularios, enviando 4 notas de voz o dictando su información.
    """

    @staticmethod
    def is_onboarding_trigger(text: str) -> bool:
        """Determines if the incoming text signals the intent to start or resume onboarding."""
        clean = (text or "").lower().strip()
        return any(trigger in clean for trigger in ONBOARDING_TRIGGERS)

    @staticmethod
    def get_or_create_session(db: Session, phone: str) -> Tuple[Prospect, Dict[str, Any]]:
        """Retrieves or initializes the active audio onboarding session for a phone number."""
        clean_phone = sanitize_phone(phone)
        prospect = db.query(Prospect).filter(
            (Prospect.phone == clean_phone) |
            (Prospect.phone == phone)
        ).first()

        if not prospect:
            session_state = {
                "step": 1,
                "collected_data": {
                    "business_name": None,
                    "owner_name": None,
                    "city": "Paraná, Entre Ríos",
                    "professionals": [],
                    "operating_hours": None,
                    "appointment_duration": "30 min",
                    "requires_deposit": False,
                    "deposit_amount": None,
                    "emergency_protocol": None,
                    "price_notes": None
                },
                "audios_count": 0,
                "history": [],
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            prospect = Prospect(
                phone=clean_phone,
                name="Profesional Salud (En Alta)",
                contact_name="Doctor/a",
                business_type="salud",
                campaign="onboarding_audio",
                status="in_progress",
                notes=json.dumps({"onboarding_session": session_state}, ensure_ascii=False)
            )
            db.add(prospect)
            db.commit()
            db.refresh(prospect)
            return prospect, session_state

        # Check existing notes for session
        session_state = None
        try:
            if prospect.notes and "onboarding_session" in prospect.notes:
                parsed = json.loads(prospect.notes)
                session_state = parsed.get("onboarding_session")
        except Exception as e:
            logger.warning(f"Error parsing onboarding session notes for {phone}: {e}")

        if not session_state:
            session_state = {
                "step": 1,
                "collected_data": {
                    "business_name": prospect.name if prospect.name and "Profesional" not in prospect.name else None,
                    "owner_name": prospect.contact_name if prospect.contact_name and "Doctor" not in prospect.contact_name else None,
                    "city": prospect.city or "Paraná, Entre Ríos",
                    "professionals": [],
                    "operating_hours": None,
                    "appointment_duration": "30 min",
                    "requires_deposit": False,
                    "deposit_amount": None,
                    "emergency_protocol": None,
                    "price_notes": None
                },
                "audios_count": 0,
                "history": [],
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            prospect.campaign = "onboarding_audio"
            prospect.status = "in_progress"
            prospect.notes = json.dumps({"onboarding_session": session_state}, ensure_ascii=False)
            db.commit()

        return prospect, session_state

    @classmethod
    async def process_step(
        cls,
        db: Session,
        phone: str,
        audio_b64: Optional[str] = None,
        audio_mime: Optional[str] = "audio/ogg",
        text: Optional[str] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Processes an incoming audio note or text message during the onboarding flow:
        1. Calls Gemini Flash multimodally with raw audio or text.
        2. Merges extracted structured data into the session knowledge base.
        3. If completed, provisions the Tenant and returns live test guidance.
        4. If more steps needed, guides the user to the next audio.
        """
        clean_phone = sanitize_phone(phone)
        prospect, session = cls.get_or_create_session(db, clean_phone)

        # Handle cancellation command
        clean_text = (text or "").strip().lower()
        if clean_text in ["cancelar", "cancelar alta", "salir", "reiniciar alta"]:
            prospect.campaign = "ai_agency"
            prospect.status = "new"
            prospect.notes = "Alta cancelada por el usuario."
            db.commit()
            return True, "🚫 *Puesta en marcha cancelada.* Cuando quieras retomarla, simplemente escribime o mandame un audio diciendo *«alta clínica»*.", {}

        collected = session.get("collected_data", {})
        step = session.get("step", 1)
        if audio_b64:
            session["audios_count"] = session.get("audios_count", 0) + 1

        gemini_data = await cls._extract_with_gemini(
            audio_b64=audio_b64,
            audio_mime=audio_mime,
            text=text,
            current_collected=collected,
            current_step=step
        )

        # Update collected data with Gemini results
        for k, v in gemini_data.get("extracted", {}).items():
            if v is not None:
                if isinstance(v, list) and k == "professionals":
                    # Append or update professionals
                    existing_prof_names = {p.get("name", "").lower() for p in collected.get("professionals", [])}
                    for new_p in v:
                        if new_p.get("name") and new_p.get("name").lower() not in existing_prof_names:
                            collected.setdefault("professionals", []).append(new_p)
                elif isinstance(v, str) and v.strip():
                    collected[k] = v.strip()
                elif isinstance(v, bool):
                    collected[k] = v

        session["collected_data"] = collected

        # Check completeness
        has_identity = bool(collected.get("business_name") and collected.get("owner_name"))
        has_hours = bool(collected.get("operating_hours"))
        has_profs = bool(collected.get("professionals") and len(collected["professionals"]) > 0)
        is_complete = gemini_data.get("is_onboarding_complete", False) or (has_identity and has_hours and has_profs and step >= 4)

        if is_complete or step >= 4:
            # Create Tenant and finalize!
            tenant, final_reply = cls._finalize_tenant(db, prospect, clean_phone, collected)
            session["step"] = 5
            session["completed_at"] = datetime.now(timezone.utc).isoformat()
            prospect.notes = json.dumps({"onboarding_session": session, "tenant_slug": tenant.slug}, ensure_ascii=False)
            db.commit()
            return True, final_reply, {"tenant_slug": tenant.slug, "is_complete": True}

        # Otherwise advance step
        next_step = step + 1
        session["step"] = next_step
        prospect.notes = json.dumps({"onboarding_session": session}, ensure_ascii=False)
        db.commit()

        # Build response
        custom_reply = gemini_data.get("conversational_reply")
        if not custom_reply:
            if next_step == 2:
                custom_reply = f"✅ *¡Excelente! Tomé nota de {collected.get('business_name', 'tu clínica')} en {collected.get('city', 'tu ciudad')}.*\n\n{DEFAULT_PROMPT_STEP_2}"
            elif next_step == 3:
                custom_reply = f"✅ *¡Anotado el equipo médico!*\n\n{DEFAULT_PROMPT_STEP_3}"
            elif next_step == 4:
                custom_reply = f"✅ *¡Horarios registrados!*\n\n{DEFAULT_PROMPT_STEP_4}"
            else:
                custom_reply = f"✅ *Datos recibidos.* Pasamos al siguiente punto."

        return True, custom_reply, {"step": next_step, "is_complete": False}

    @classmethod
    async def _extract_with_gemini(
        cls,
        audio_b64: Optional[str],
        audio_mime: Optional[str],
        text: Optional[str],
        current_collected: Dict[str, Any],
        current_step: int
    ) -> Dict[str, Any]:
        """Invokes Gemini Flash multimodal natively to parse voice note or text into clinic schema."""
        gemini_key = settings.GEMINI_API_KEY
        if not gemini_key:
            return cls._rule_based_fallback(text, current_collected, current_step)

        clean_mime = (audio_mime or "audio/ogg").split(";")[0].strip()
        system_instruction = (
            "Sos el motor de Onboarding Operativo para Clínicas y Consultorios Médicos de Sofía AI Agency en Argentina.\n"
            "Tu objetivo es escuchar notas de voz o leer mensajes de los médicos/titulares y extraer estructuradamente su información operativa.\n"
            "Debes ser flexible: si el usuario dice en un solo audio cosas correspondientes a varios pasos, extraelas todas sin problema.\n"
            "Reconocé modismos argentinos, obras sociales locales (OSDE, Swiss Medical, Galeno, Jerárquicos, IOMA, PAMI, etc.) y especialidades médicas.\n\n"
            "Respondé ÚNICAMENTE un JSON válido con esta estructura exacta:\n"
            "{\n"
            "  \"extracted\": {\n"
            "    \"business_name\": \"Nombre de la clínica/consultorio o null\",\n"
            "    \"owner_name\": \"Nombre del titular con título (ej: Dr. Carlos Gómez) o null\",\n"
            "    \"city\": \"Ciudad y provincia o null\",\n"
            "    \"professionals\": [\n"
            "      {\"name\": \"Dr. ...\", \"specialty\": \"...\", \"insurances\": [\"OSDE\", \"Particular\"]}\n"
            "    ],\n"
            "    \"operating_hours\": \"Días y rangos horarios (ej: Lunes a Viernes de 8:30 a 12:30 y 16:00 a 20:00) o null\",\n"
            "    \"appointment_duration\": \"30 min / 45 min / etc o null\",\n"
            "    \"requires_deposit\": true / false / null,\n"
            "    \"deposit_amount\": \"Monto si aplica o null\",\n"
            "    \"emergency_protocol\": \"Protocolo ante dolor urgente o null\",\n"
            "    \"price_notes\": \"Aranceles o notas o null\"\n"
            "  },\n"
            "  \"is_onboarding_complete\": false,\n"
            "  \"conversational_reply\": \"Mensaje argentino, cálido, ejecutivo y conciso para WhatsApp confirmando lo entendido y pidiendo amablemente el siguiente audio.\"\n"
            "}"
        )

        prompt_text = (
            f"DATOS ACTUALES YA RECOLECTADOS:\n{json.dumps(current_collected, ensure_ascii=False, indent=2)}\n\n"
            f"PASO ACTUAL ESPERADO: Audio {current_step} de 4.\n"
            f"{'Texto adjunto: ' + text if text else 'Audio de voz recibido por WhatsApp.'}\n"
            f"Escuchá/leé el contenido, combiná con los datos actuales y devolvé el JSON pedido."
        )

        parts = []
        if audio_b64:
            parts.append({"inline_data": {"mime_type": clean_mime, "data": audio_b64}})
        parts.append({"text": prompt_text})

        payload = {
            "contents": [{"parts": parts}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": 0.2,
                "response_mime_type": "application/json"
            }
        }

        candidate_models = ["gemini-flash-lite-latest", "gemini-3.6-flash", "gemini-3.5-flash-lite"]
        for model_name in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(url, json=payload)
                    if res.status_code == 200:
                        raw = res.json()
                        candidates = raw.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            part = candidates[0]["content"].get("parts", [{}])[0]
                            text_out = part.get("text", "").strip()
                            if text_out:
                                if "```json" in text_out:
                                    text_out = text_out.split("```json")[1].split("```")[0].strip()
                                elif "```" in text_out:
                                    text_out = text_out.split("```")[1].split("```")[0].strip()
                                parsed = json.loads(text_out)
                                logger.info(f"🎙️ Gemini Flash extracted clinic onboarding data via {model_name}")
                                return parsed
                    else:
                        logger.warning(f"Gemini {model_name} status {res.status_code}: {res.text[:120]}")
            except Exception as e:
                logger.warning(f"Error calling {model_name} for audio onboarding: {e}")

        return cls._rule_based_fallback(text, current_collected, current_step)

    @classmethod
    def _rule_based_fallback(
        cls,
        text: Optional[str],
        current_collected: Dict[str, Any],
        current_step: int
    ) -> Dict[str, Any]:
        """Rule-based extractor for test suites or offline environments without active API keys."""
        extracted: Dict[str, Any] = {}
        t_clean = (text or "").strip()
        t_low = t_clean.lower()

        # Step 1: Identity & City
        if current_step == 1 or not current_collected.get("business_name"):
            name_m = re.search(r'(?:somos|clinica|clínica|consultorio|consultorios)\s+([A-Za-z0-9\s]+?)(?:\sen|\scon|\sy|\.|$)', t_clean, re.I)
            if name_m:
                extracted["business_name"] = name_m.group(0).strip().capitalize()
            elif len(t_clean) > 3 and current_step == 1:
                extracted["business_name"] = t_clean.title()

            doc_m = re.search(r'(?:dr\.|dr|dra\.|dra|doctor|doctora)\s+([A-Za-z\s]+)', t_clean, re.I)
            if doc_m:
                extracted["owner_name"] = doc_m.group(0).strip().title()
            
            city_m = re.search(r'(?:en|de)\s+([A-Za-z\s]+?(?:ríos|santa fe|buenos aires|córdoba|cordoba|paraná|parana))', t_low)
            if city_m:
                extracted["city"] = city_m.group(1).strip().title()

        # Step 2: Professionals & Insurances
        if current_step == 2 or "atiende" in t_low or "dr" in t_low or "odont" in t_low:
            profs = []
            if "osde" in t_low or "particular" in t_low or "swiss" in t_low:
                insurances = []
                for ins in ["OSDE", "Swiss Medical", "Galeno", "Particular", "IOMA", "PAMI"]:
                    if ins.lower() in t_low:
                        insurances.append(ins)
                owner = current_collected.get("owner_name") or "Dr. Responsable"
                profs.append({
                    "name": owner,
                    "specialty": "Odontología / Consulta General",
                    "insurances": insurances or ["Particular"]
                })
                extracted["professionals"] = profs

        # Step 3: Schedules & Duration
        if current_step == 3 or any(w in t_low for w in ["lunes", "viernes", "horas", "horario", "minutos"]):
            extracted["operating_hours"] = t_clean or "Lunes a Viernes de 8:30 a 12:30 y 16:00 a 20:00"
            if "45" in t_low:
                extracted["appointment_duration"] = "45 min"
            elif "60" in t_low or "hora" in t_low:
                extracted["appointment_duration"] = "60 min"
            else:
                extracted["appointment_duration"] = "30 min"

        # Step 4: Fees & Deposits
        if current_step == 4 or any(w in t_low for w in ["seña", "sena", "consulta", "cobro", "precio", "urgencia"]):
            extracted["requires_deposit"] = "si" in t_low or "sí" in t_low or "seña" in t_low
            extracted["price_notes"] = t_clean

        is_complete = current_step >= 4
        return {
            "extracted": extracted,
            "is_onboarding_complete": is_complete,
            "conversational_reply": None
        }

    @classmethod
    def _finalize_tenant(
        cls,
        db: Session,
        prospect: Prospect,
        clean_phone: str,
        collected: Dict[str, Any]
    ) -> Tuple[Tenant, str]:
        """Creates the official Tenant record, configures modules, and returns the final celebration message."""
        biz_name = collected.get("business_name") or "Consultorios Médicos"
        owner_name = collected.get("owner_name") or "Dr. Responsable"
        city = collected.get("city") or "Paraná, Entre Ríos"
        operating_hours = collected.get("operating_hours") or "Lunes a Viernes de 8:30 a 12:30 y 16:00 a 20:00"
        duration = collected.get("appointment_duration") or "30 min"

        slug = generate_safe_slug(biz_name, db)

        kb_data = {
            "business_name": biz_name,
            "business_type": "salud",
            "owner_name": owner_name,
            "owner_phone": clean_phone,
            "city": city,
            "operating_hours": operating_hours,
            "appointment_duration": duration,
            "requires_deposit": bool(collected.get("requires_deposit", False)),
            "deposit_amount": collected.get("deposit_amount"),
            "emergency_protocol": collected.get("emergency_protocol"),
            "professionals": collected.get("professionals", []),
            "price_notes": collected.get("price_notes"),
            "onboarding_channel": "whatsapp_audio",
            "created_via": "audio_onboarding_gemini",
            "submitted_at": datetime.now(timezone.utc).isoformat()
        }

        tenant = Tenant(
            slug=slug,
            name=biz_name,
            business_type="salud",
            owner_phone=clean_phone,
            owner_name=owner_name,
            deep_link_keyword=slug.capitalize(),
            modules_enabled=json.dumps(["turnos_rellena_huecos", "recordatorios", "faq"]),
            knowledge_base=json.dumps(kb_data, ensure_ascii=False),
            plan_type="shared",
            monthly_message_quota=150,
            active=True
        )
        db.add(tenant)

        prospect.name = biz_name
        prospect.contact_name = owner_name
        prospect.campaign = "client_onboarding"
        prospect.status = "onboarded"
        prospect.city = city
        prospect.notes = f"Tenant ID: {slug} | Alta exitosa por 4 Audios de WhatsApp"
        db.commit()
        db.refresh(tenant)

        # Notify Javier (Admin Alert)
        boss_phone = "".join(filter(str.isdigit, str(settings.WHATSAPP_ALERT_PHONE or "5493434536447")))
        if boss_phone:
            alert_text = (
                f"🎉 *[NUEVA ALTA DE CLÍNICA POR AUDIO WHATSAPP]* 🚀\n\n"
                f"🏥 *Clínica:* {biz_name} (`{slug}`)\n"
                f"👨‍⚕️ *Titular:* {owner_name}\n"
                f"📱 *WhatsApp:* +{clean_phone}\n"
                f"📍 *Ciudad:* {city}\n"
                f"⏰ *Horarios:* {operating_hours}\n"
                f"⏱️ *Turnos:* {duration}\n"
                f"👥 *Profesionales:* {len(collected.get('professionals', []))} registrados\n"
                f"🏷️ *Plan:* A medida según escala\n\n"
                f"👉 ¡Sofía ya está calibrada y lista para recibir pacientes!"
            )
            asyncio.create_task(whatsapp.send_whatsapp_message(to_phone=boss_phone, text=alert_text))

        # Format professionals list for display
        profs_display = ""
        for p in collected.get("professionals", []):
            p_name = p.get("name", "Profesional")
            p_spec = p.get("specialty", "Salud")
            profs_display += f"  • *{p_name}* ({p_spec})\n"
        if not profs_display:
            profs_display = f"  • *{owner_name}* (Atención General)\n"

        deposit_text = f"Sí (${collected.get('deposit_amount', 'A coordinar')})" if collected.get("requires_deposit") else "No, abonan al asistir"

        agent_number = "".join(filter(str.isdigit, str(settings.WHATSAPP_AGENT_PHONE or "5493435720312")))
        keyword = tenant.deep_link_keyword or slug
        direct_link = f"https://wa.me/{agent_number}?text=Hola%20quiero%20turno%20en%20{keyword}"
        poster_link = f"https://sofia-ai-agency.onrender.com/acceso/{slug}"

        celebration_message = (
            f"🚀 *¡FELICITACIONES! {biz_name.upper()} YA ESTÁ ACTIVO EN SOFÍA* 🏥\n\n"
            f"Configuré tu consultorio en base a tus audios:\n"
            f"📍 *Ubicación:* {city}\n"
            f"👨‍⚕️ *Profesional Responsable:* {owner_name}\n"
            f"👥 *Equipo Médico:*\n{profs_display}"
            f"⏰ *Horarios de Atención:* {operating_hours}\n"
            f"⏱️ *Duración de Turno:* {duration}\n"
            f"💵 *Seña previa:* {deposit_text}\n\n"
            f"📲 *TU ENLACE DIRECTO DE WHATSAPP:*\n"
            f"{direct_link}\n"
            f"_(Pegalo en tu perfil de Instagram o en el botón de WhatsApp de Google Maps)_\n\n"
            f"🖨️ *TU CARTEL IMPRIMIBLE CON CÓDIGO QR:*\n"
            f"{poster_link}\n"
            f"_(Abrilo desde tu PC o celular para imprimir tu cartel oficial de recepción)_\n\n"
            f"🛡️ *MÓDULOS ACTIVOS DE SOFÍA:*\n"
            f"✅ *Toma de Turnos 24/7:* Sin superposiciones de horarios.\n"
            f"✅ *Recordatorios Automáticos:* Sofía contacta al paciente 24hs antes para confirmar.\n"
            f"✅ *Rellena-Huecos Inteligente:* Ante cualquier cancelación, ofrece el turno a la lista de espera.\n"
            f"✅ *RAG Orgánico:* Cualquier consulta que Sofía no sepa, te la preguntará por acá para aprenderla.\n"
            f"✅ *Modo Jefe:* Podés dictarle directivas a Sofía desde tu celular cuando quieras.\n\n"
            f"🎯 *¿CÓMO PROBARLO AHORA MISMO?*\n"
            f"Escribile a este número desde otro celular como si fueras un paciente nuevo:\n"
            f"_«Hola, quisiera un turno para mañana con {owner_name}»_\n"
            f"¡Y mirá cómo responde en tiempo real!"
        )

        return tenant, celebration_message


audio_onboarding_service = AudioOnboardingService()
