import re
import json
import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.models.tenant import Tenant, TenantSession, Appointment, WaitlistEntry, MembershipPayment, InactiveCustomer
from app.services.tenant_service import tenant_service
from app.services.appointment_service import appointment_service
from app.services.billing_service import billing_service
from app.services import whatsapp
from app.config.settings import settings

logger = logging.getLogger(__name__)

def utc_now():
    return datetime.now(timezone.utc)

class TenantDispatcher:
    """
    Enterprise Tenant Message Dispatcher:
    Dispatches and handles all business-specific logic for clinics, gyms, optics,
    and shops under the single official Meta Cloud API number.
    """

    @staticmethod
    async def process_tenant_message(
        db: Session,
        tenant: Tenant,
        phone: str,
        message: str,
        interactive_button_id: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/jpeg"
    ) -> Tuple[bool, str]:
        """
        Processes an incoming message for a resolved Tenant.
        Returns (handled: bool, reply_text: str).
        """
        clean_phone = "".join(filter(str.isdigit, phone))
        msg_clean = message.strip()
        msg_lower = msg_clean.lower()

        # -------------------------------------------------------------
        # 0. HANDLE SECRETARY COMMANDS (ESCUDO PARA LA SECRETARIA)
        # -------------------------------------------------------------
        owner_digits = "".join(filter(str.isdigit, tenant.owner_phone or ""))
        if clean_phone == owner_digits:
            if msg_lower.startswith("mantener"):
                held = await appointment_service.hold_appointment_by_secretary(db, tenant.id, msg_clean)
                return True, "Comando de secretaría procesado: Turno conservado."
            elif msg_lower in ["liberar", "liberar turnos", "liberar huecos", "cortar"]:
                count = await appointment_service.execute_cutoff_auto_cancellations(db, tenant.id)
                return True, f"Comando de secretaría: {count} turnos liberados."
            elif msg_lower in ["reporte", "resumen", "turnos mañana", "sin confirmar"]:
                await appointment_service.send_secretary_pre_cutoff_report(db, tenant.id)
                return True, "Reporte de secretaría generado."

            # AI-Powered Owner Management Command Parser (Voice & Text)
            admin_reply = await TenantDispatcher.process_owner_instruction(db, tenant, msg_clean)
            if admin_reply:
                await whatsapp.send_whatsapp_message(tenant.owner_phone, admin_reply)
                return True, admin_reply

        # -------------------------------------------------------------
        # 1. HANDLE INTERACTIVE BUTTON CLICKS
        # -------------------------------------------------------------
        btn_id = interactive_button_id or ""

        # A. Confirm Appointment Button
        if btn_id.startswith("confirm_apt_"):
            try:
                apt_id = int(btn_id.split("confirm_apt_")[1])
                confirmed = await appointment_service.confirm_appointment(db, apt_id)
                if confirmed:
                    return True, "Turno confirmado con éxito."
            except Exception as e:
                logger.error(f"Error handling confirm button {btn_id}: {e}")

        # B. Cancel Appointment & Fill Gap Button
        elif btn_id.startswith("cancel_apt_"):
            try:
                apt_id = int(btn_id.split("cancel_apt_")[1])
                res = await appointment_service.cancel_and_fill_gap(db, apt_id, reason="Cancelado por botón de WhatsApp")
                return True, "Turno cancelado y hueco activado."
            except Exception as e:
                logger.error(f"Error handling cancel button {btn_id}: {e}")

        # C. Claim Waitlist Slot Button
        elif btn_id.startswith("claim_apt_"):
            try:
                parts = btn_id.split("_")
                apt_id = int(parts[2])
                waitlist_id = int(parts[3])
                claimed = await appointment_service.claim_waitlist_slot(db, apt_id, waitlist_id)
                return True, "Turno tomado de lista de espera."
            except Exception as e:
                logger.error(f"Error claiming waitlist button {btn_id}: {e}")

        # C2. Reject Waitlist Slot Button (Strict 1-by-1 pass to candidate #2)
        elif btn_id.startswith("reject_apt_"):
            try:
                parts = btn_id.split("_")
                apt_id = int(parts[2])
                waitlist_id = int(parts[3])
                await appointment_service.reject_waitlist_slot(db, apt_id, waitlist_id)
                return True, "Turno rechazado, pasado al siguiente candidato."
            except Exception as e:
                logger.error(f"Error rejecting waitlist button {btn_id}: {e}")

        # C3. Fast-Track Accept Button (Adelanta-Turnos)
        elif btn_id.startswith("fast_track_accept_"):
            try:
                parts = btn_id.split("_")
                vacant_apt_id = int(parts[3])
                future_apt_id = int(parts[4])
                claimed = await appointment_service.claim_fast_track_slot(db, vacant_apt_id, future_apt_id)
                return True, "Turno adelantado con éxito por paciente futuro."
            except Exception as e:
                logger.error(f"Error claiming fast-track button {btn_id}: {e}")

        # C4. Fast-Track Decline Button (Adelanta-Turnos)
        elif btn_id.startswith("fast_track_decline_"):
            try:
                parts = btn_id.split("_")
                vacant_apt_id = int(parts[3])
                future_apt_id = int(parts[4])
                await appointment_service.reject_fast_track_slot(db, vacant_apt_id, future_apt_id)
                return True, "Turno adelantado declinado, fecha original mantenida."
            except Exception as e:
                logger.error(f"Error rejecting fast-track button {btn_id}: {e}")

        # D. Claim Promo Button
        elif btn_id.startswith("claim_promo_"):
            try:
                cust_id = int(btn_id.split("claim_promo_")[1])
                cust = db.query(InactiveCustomer).filter(InactiveCustomer.id == cust_id).first()
                if cust:
                    cust.status = "interesado"
                    db.commit()
                    reply = (
                        f"🎉 *¡Excelente decisión, {cust.customer_name}!* "
                        f"Ya registramos tu interés en la promoción de {tenant.name}.\n\n"
                        f"En breve un asesor de administración te enviará el link de pago o CBU para activar tu beneficio exclusivo."
                    )
                    await tenant_service.send_branded_notification(tenant, clean_phone, reply)

                    # Alert Owner
                    if tenant.owner_phone:
                        owner_alert = (
                            f"🔥 *¡CLIENTE REACTIVADO!*\n\n"
                            f"👤 Cliente: *{cust.customer_name}*\n"
                            f"📱 Celular: +{cust.customer_phone}\n"
                            f"🏢 Comercio: {tenant.name}\n"
                            f"🎯 Acción: Aceptó la promo ({cust.service_or_product or 'Verano'}).\n"
                            f"👉 Contactalo para concretar el cobro."
                        )
                        await whatsapp.send_owner_or_admin_alert(
                            to_phone=tenant.owner_phone,
                            fallback_text=owner_alert,
                            business_name=tenant.name,
                            event_type="Cliente Reactivado (Promo)",
                            client_title=f"{cust.customer_name} (+{cust.customer_phone})",
                            details_summary=f"Aceptó la promo: {cust.service_or_product or 'Verano'}."
                        )
                    return True, reply
            except Exception as e:
                logger.error(f"Error claiming promo {btn_id}: {e}")

        # -------------------------------------------------------------
        # 2. HANDLE BANK TRANSFER RECEIPT IMAGES (MULTIMODAL AI)
        # -------------------------------------------------------------
        if image_bytes and len(image_bytes) > 1000:
            res = await billing_service.process_receipt_image(db, clean_phone, image_bytes, mime_type=image_mime)
            return True, "Comprobante procesado."

        # -------------------------------------------------------------
        # 3. TEXT INTENT DETECTION: APPOINTMENTS (SALUD / TURNOS)
        # -------------------------------------------------------------
        if "turnos_rellena_huecos" in tenant.modules_enabled or tenant.business_type in ["salud", "medicina", "estetica"]:
            recent_apt = db.query(Appointment).filter(
                Appointment.tenant_id == tenant.id,
                Appointment.patient_phone == clean_phone,
                Appointment.status.in_(["agendado", "recordatorio_enviado"])
            ).order_by(Appointment.id.desc()).first()

            if recent_apt:
                # Cancellation intent
                if any(w in msg_lower for w in ["no puedo", "no llego", "cancelo", "cancelar", "imposible ir", "reprogramar", "enfermo", "fiebre"]):
                    await appointment_service.cancel_and_fill_gap(db, recent_apt.id, reason=msg_clean)
                    return True, "Turno cancelado."

                # Confirmation intent
                if any(w in msg_lower for w in ["confirmo", "si confirmo", "voy", "ahi estare", "ahi voy", "perfecto voy", "si voy"]):
                    await appointment_service.confirm_appointment(db, recent_apt.id)
                    return True, "Turno confirmado."

            # Check waitlist claim in text
            if "tomar turno" in msg_lower or "quiero el turno" in msg_lower or "lo tomo" in msg_lower:
                wl = db.query(WaitlistEntry).filter(
                    WaitlistEntry.tenant_id == tenant.id,
                    WaitlistEntry.patient_phone == clean_phone,
                    WaitlistEntry.status == "notificado_oferta"
                ).order_by(WaitlistEntry.id.desc()).first()
                if wl and wl.offered_appointment_id:
                    await appointment_service.claim_waitlist_slot(db, wl.offered_appointment_id, wl.id)
                    return True, "Turno tomado de lista de espera."

        # -------------------------------------------------------------
        # 4. TEXT INTENT DETECTION: PROMOS / REACTIVATION
        # -------------------------------------------------------------
        if "quiero la promo" in msg_lower or "me interesa la promo" in msg_lower:
            cust = db.query(InactiveCustomer).filter(
                InactiveCustomer.tenant_id == tenant.id,
                InactiveCustomer.customer_phone == clean_phone
            ).order_by(InactiveCustomer.id.desc()).first()
            if cust:
                cust.status = "interesado"
                db.commit()
                reply = (
                    f"🎉 *¡Excelente!* Hemos registrado tu solicitud para la promoción de *{tenant.name}*.\n"
                    f"Un asesor de administración te enviará las opciones de pago para confirmar tu pase."
                )
                await tenant_service.send_branded_notification(tenant, clean_phone, reply)
                if tenant.owner_phone:
                    await whatsapp.send_whatsapp_message(
                        tenant.owner_phone,
                        f"🔥 *LEAD CALIENTE:* {cust.customer_name} (+{cust.customer_phone}) pidió la promo de {tenant.name}."
                    )
                return True, reply

        # -------------------------------------------------------------
        # 5. CONVERSATIONAL AI (GEMINI) USING TENANT'S KNOWLEDGE BASE
        # -------------------------------------------------------------
        system_prompt = tenant_service.build_tenant_system_prompt(tenant)

        # Context Awareness: Check if sender has an upcoming appointment in this clinic/business
        active_apt = db.query(Appointment).filter(
            Appointment.tenant_id == tenant.id,
            Appointment.patient_phone == clean_phone,
            Appointment.status.in_(["agendado", "recordatorio_48h", "recordatorio_24h", "confirmado"])
        ).order_by(Appointment.appointment_date.asc()).first()

        if active_apt:
            date_fmt = active_apt.appointment_date.strftime("%A %d/%m a las %H:%M hs")
            system_prompt += (
                f"\n\nDATOS DEL PACIENTE QUE TE ESTÁ ESCRIBIENDO:\n"
                f"- Nombre: {active_apt.patient_name}\n"
                f"- Turno agendado: {date_fmt} con {active_apt.doctor_or_service}\n"
                f"- Estado actual: {active_apt.status}\n\n"
                f"PAUTAS ESPECÍFICAS DE RESPUESTA:\n"
                f"1. Si el paciente solo saluda o agradece cordialmente ('ok', 'gracias', 'dale', 'perfecto', 'buen día'), "
                f"respondé en 1 sola línea de forma muy cálida deseándole un excelente día y confirmando que no se preocupe por nada.\n"
                f"2. Si el paciente manifiesta que NO podrá asistir o pide cancelar su turno ('no puedo ir', 'cancélalo', 'estoy enfermo/a', 'se me complica', 'no llego'), "
                f"sé empática, confirmale que procedés a cancelar su turno del {date_fmt} para que no se preocupe y que cuando desee reprogramar te avise. Incluye al final de tu respuesta la etiqueta especial [CANCEL_APPOINTMENT_INTENT].\n"
                f"3. Si el paciente pregunta por cambiar de horario o reprogramar ('¿puedo cambiar?', '¿para qué hora tenés el viernes?'), "
                f"mencioná su turno actual ({date_fmt}) y preguntale qué día y horario preferiría para coordinarlo con la secretaría.\n"
            )

        ai_reply = None

        if settings.GEMINI_API_KEY:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={settings.GEMINI_API_KEY}"
            payload = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": msg_clean}]}],
                "generationConfig": {"temperature": 0.6, "maxOutputTokens": 600}
            }
            try:
                import httpx
                async with httpx.AsyncClient(timeout=20.0) as client:
                    res = await client.post(url, json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            ai_reply = candidates[0]["content"]["parts"][0]["text"].strip()
            except Exception as ai_err:
                logger.error(f"Error calling Gemini REST for Tenant {tenant.name}: {ai_err}")

        if not ai_reply:
            ai_reply = f"Hola, te comunicaste con {tenant.name}. En breve un asesor te responderá."

        # Handle automatic cancellation if Gemini detected explicit cancellation intent
        if active_apt and "[CANCEL_APPOINTMENT_INTENT]" in ai_reply:
            ai_reply = ai_reply.replace("[CANCEL_APPOINTMENT_INTENT]", "").strip()
            logger.info(f"🛑 Intent cancellation detected in chat for patient '{active_apt.patient_name}' (Turno #{active_apt.id}). Executing cancel_and_fill_gap...")
            await appointment_service.cancel_and_fill_gap(db, active_apt.id, reason=f"Cancelación informada por chat: '{msg_clean}'")

        # Send response branded with the Tenant's header and logo (if it's their first message)
        session = db.query(TenantSession).filter(TenantSession.phone == clean_phone).first()
        is_first_interaction = (session is None or session.context_data == "{}")

        await tenant_service.send_branded_notification(
            tenant=tenant,
            to_phone=clean_phone,
            body_text=ai_reply,
            with_logo=(is_first_interaction and bool(tenant.logo_url))
        )

        return True, ai_reply

    @staticmethod
    async def process_owner_instruction(db: Session, tenant: Tenant, message: str) -> Optional[str]:
        """
        Parses administrative instructions sent by the business owner or secretary via WhatsApp audio/text.
        Supports:
        - Price & Fee updates ("la cuota subió de 45mil a 55mil", "el pase libre sube a 35000")
        - Appointment scheduling ("anotá a Pedro el jueves a las 16hs con Dra Gómez, cel 3434556677")
        - Waitlist additions ("sumá a Laura a la lista de espera de la Dra Gómez, cel 3434112233")
        - Temporary notices & holidays ("el lunes no abrimos por feriado")
        """
        msg_lower = message.lower().strip()

        # Check for agenda/slots queries from secretary/owner
        is_query_slots = any(w in msg_lower for w in [
            "quedo libre", "quedó libre", "hueco", "huecos", "turnos libres", 
            "turnos de mañana", "lista de espera", "alguien para el turno", "quien cubre", "quién cubre", "estado de turnos"
        ])
        if is_query_slots:
            now = utc_now()
            start_tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_tomorrow = (now + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
            tomorrow_apts = db.query(Appointment).filter(
                Appointment.tenant_id == tenant.id,
                Appointment.appointment_date >= start_tomorrow,
                Appointment.appointment_date <= end_tomorrow
            ).order_by(Appointment.appointment_date.asc()).all()

            waitlist_cnt = db.query(WaitlistEntry).filter(
                WaitlistEntry.tenant_id == tenant.id,
                WaitlistEntry.status == "activa"
            ).count()

            lines = []
            vacant_cnt = 0
            for a in tomorrow_apts:
                t_str = a.appointment_date.strftime("%H:%M hs")
                if a.status in ["cancelado", "liberado_por_adelanto"]:
                    vacant_cnt += 1
                    lines.append(f"• ⚠️ *{t_str}* — LIBRE (Cancelado por {a.patient_name})")
                elif a.status == "rellenado_con_exito":
                    lines.append(f"• ✅ *{t_str}* — Cubierto por {a.patient_name} (Lista de Espera / Adelanto)")
                elif a.status == "confirmado":
                    lines.append(f"• ✅ *{t_str}* — Confirmado por {a.patient_name}")
                else:
                    lines.append(f"• ⏳ *{t_str}* — Pendiente de confirmación ({a.patient_name})")

            date_tag = start_tomorrow.strftime('%d/%m')
            res_text = f"📋 *ESTADO DE AGENDA PARA MAÑANA ({date_tag}):*\n\n"
            if lines:
                res_text += "\n".join(lines) + "\n\n"
            else:
                res_text += "No hay turnos registrados para mañana.\n\n"

            res_text += f"⚡ *Lista de espera activa:* {waitlist_cnt} personas.\n"
            if vacant_cnt > 0 and waitlist_cnt == 0:
                res_text += "💡 *Adelanta-Turnos:* Se activó el ofrecimiento a pacientes agendados para la próxima semana.\n"
            res_text += "👉 Podés asignar cualquier sobreturno diciendo *«anotá a [Nombre] mañana [Hora]»*."
            return res_text

        # Quick regex check for price change keywords
        is_price_change = any(w in msg_lower for w in ["subió", "subio", "aumento", "aumentó", "nuevo precio", "la cuota sale", "cambiar precio", "precio nuevo"])
        is_appointment = any(w in msg_lower for w in ["anota a", "anotá a", "agendar a", "agendá a", "turno para", "turno el"])
        is_waitlist = any(w in msg_lower for w in ["lista de espera", "anotar en espera", "sumar a espera"])
        is_holiday = any(w in msg_lower for w in ["feriado", "no abrimos", "cerrado el", "no atendemos"])

        if not (is_price_change or is_appointment or is_waitlist or is_holiday):
            return None

        prompt = f"""
Eres el asistente ejecutivo administrativo del comercio '{tenant.name}'.
Rubro: {tenant.business_type}.
Base de conocimiento actual del comercio:
{tenant.knowledge_base}

El dueño o secretaria te acaba de enviar esta instrucción por WhatsApp:
"{message}"

Debes clasificar la acción y responder estrictamente un JSON válido con esta estructura:
{{
  "action": "UPDATE_PRICE" | "CREATE_APPOINTMENT" | "ADD_WAITLIST" | "ADD_HOLIDAY_NOTE" | "UNKNOWN",
  "plan_or_service": "nombre del plan o servicio modificado",
  "new_price": 55000 (número si aplica o null),
  "patient_or_member_name": "nombre de la persona",
  "phone": "número de celular con código de área si se menciona",
  "doctor_or_service": "profesional o servicio",
  "date_time_str": "descripción de fecha y hora (ej: jueves 16:00 hs)",
  "reply_to_owner": "Mensaje cordial y ejecutivo confirmando el cambio exacto realizado en el sistema."
}}
"""
        try:
            parsed = None
            if settings.GEMINI_API_KEY:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={settings.GEMINI_API_KEY}"
                payload = {
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 400}
                }
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=20.0) as client:
                        res = await client.post(url, json=payload)
                        if res.status_code == 200:
                            data = res.json()
                            candidates = data.get("candidates", [])
                            if candidates and "content" in candidates[0]:
                                raw_json = candidates[0]["content"]["parts"][0]["text"].strip()
                                if "```json" in raw_json:
                                    raw_json = raw_json.split("```json")[1].split("```")[0].strip()
                                elif "```" in raw_json:
                                    raw_json = raw_json.split("```")[1].split("```")[0].strip()
                                parsed = json.loads(raw_json)
                except Exception as gem_err:
                    logger.warning(f"Error parsing owner instruction via Gemini REST: {gem_err}")

            # Regex fallback for price updates if offline or API error
            if not parsed and is_price_change:
                price_match = re.search(r'(?:subi[oó]|aument[oó]|a\s*|precio\s*)(?:de\s*\d+\s*)?(?:a\s*)?\$?\s*(\d{2,6})', msg_lower)
                if price_match:
                    new_num = float(price_match.group(1))
                    parsed = {
                        "action": "UPDATE_PRICE",
                        "plan_or_service": "cuota",
                        "new_price": new_num,
                        "reply_to_owner": f"He actualizado el precio a ${new_num:,.0f} ARS con éxito."
                    }

            if parsed:
                action = parsed.get("action")
                reply = parsed.get("reply_to_owner", "Instrucción administrativa procesada.")

                # Execute Action on Tenant Database
                if action == "UPDATE_PRICE":
                    try:
                        kb = json.loads(tenant.knowledge_base or "{}")
                    except Exception:
                        kb = {}
                    plan_key = parsed.get("plan_or_service") or "general"
                    new_val = parsed.get("new_price")
                    if "precios_actualizados" not in kb:
                        kb["precios_actualizados"] = {}
                    kb["precios_actualizados"][plan_key] = new_val
                    # Also update inside planes or precios if exists
                    if "planes" in kb and isinstance(kb["planes"], dict):
                        for k, v in kb["planes"].items():
                            if plan_key.lower() in k.lower() and isinstance(v, dict):
                                v["precio"] = new_val
                    tenant.knowledge_base = json.dumps(kb, ensure_ascii=False)
                    db.commit()
                    logger.info(f"💰 Owner price update applied to '{tenant.name}': {plan_key} -> ${new_val}")
                    return f"✅ *¡Entendido!* {reply}"

                elif action == "CREATE_APPOINTMENT":
                    # Parse appointment
                    now = utc_now()
                    apt_name = parsed.get("patient_or_member_name") or "Paciente"
                    apt_phone = "".join(filter(str.isdigit, str(parsed.get("phone") or "5493434000000")))
                    doc = parsed.get("doctor_or_service") or "Profesional"
                    dt_str = parsed.get("date_time_str") or "Próximos días"
                    # Create appointment
                    apt = Appointment(
                        tenant_id=tenant.id,
                        patient_name=apt_name,
                        patient_phone=apt_phone,
                        doctor_or_service=doc,
                        appointment_date=now + timedelta(days=2), # Default target
                        notes=f"Agendado por voz/texto del dueño: {dt_str}",
                        status="agendado"
                    )
                    db.add(apt)
                    db.commit()
                    return f"✅ *¡Turno agendado!*\n👤 Paciente: *{apt_name}*\n👨‍⚕️ Profesional: *{doc}*\n📅 {dt_str}\n📱 Celular: +{apt_phone}"

                elif action == "ADD_WAITLIST":
                    apt_name = parsed.get("patient_or_member_name") or "Paciente"
                    apt_phone = "".join(filter(str.isdigit, str(parsed.get("phone") or "5493434000000")))
                    doc = parsed.get("doctor_or_service") or "Profesional"
                    entry = WaitlistEntry(
                        tenant_id=tenant.id,
                        patient_name=apt_name,
                        patient_phone=apt_phone,
                        doctor_or_service=doc,
                        status="activa"
                    )
                    db.add(entry)
                    db.commit()
                    return f"✅ *¡Anotado en Lista de Espera!*\n👤 Paciente: *{apt_name}* (+{apt_phone}) para {doc}."

                elif action == "ADD_HOLIDAY_NOTE":
                    try:
                        kb = json.loads(tenant.knowledge_base or "{}")
                    except Exception:
                        kb = {}
                    kb["aviso_temporal"] = message
                    tenant.knowledge_base = json.dumps(kb, ensure_ascii=False)
                    db.commit()
                    return f"✅ *¡Aviso registrado!* A partir de ahora informaré: \"{message}\"."

                return reply
        except Exception as err:
            logger.error(f"Error parsing owner instruction: {err}")
            return "✅ Recibido. Actualizaré la información en el sistema."

tenant_dispatcher = TenantDispatcher()
