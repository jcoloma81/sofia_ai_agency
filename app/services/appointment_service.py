import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.models.tenant import Tenant, Appointment, WaitlistEntry
from app.services import whatsapp
from app.services.tenant_service import tenant_service

logger = logging.getLogger(__name__)

def utc_now():
    return datetime.now(timezone.utc)

def format_appointment_datetime(dt: datetime, include_day_name: bool = False) -> str:
    """
    Bulletproof Spanish date formatter for Argentina (UTC-3).
    Converts UTC datetime to Argentina local time and translates day names to Spanish.
    """
    if not dt:
        return ""
    if dt.tzinfo is not None:
        local_dt = dt.astimezone(timezone(timedelta(hours=-3)))
    else:
        local_dt = dt - timedelta(hours=3)

    day_names = {
        0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves",
        4: "Viernes", 5: "Sábado", 6: "Domingo"
    }
    time_str = local_dt.strftime("%d/%m a las %H:%M hs")
    if include_day_name:
        day_es = day_names.get(local_dt.weekday(), "")
        return f"{day_es} {time_str}"
    return time_str

def _get_booking_anticipation_hours(apt: Appointment) -> Optional[float]:
    """Returns how many hours in advance the appointment was booked relative to its slot date."""
    if not apt.created_at or not apt.appointment_date:
        return None
    apt_dt = apt.appointment_date.replace(tzinfo=timezone.utc) if apt.appointment_date.tzinfo is None else apt.appointment_date
    created_dt = apt.created_at.replace(tzinfo=timezone.utc) if apt.created_at.tzinfo is None else apt.created_at
    return (apt_dt - created_dt).total_seconds() / 3600.0

class AppointmentService:
    """
    Automated Medical & Professional Appointment Engine:
    - 48h & 24h Dual-Stage Scheduled Reminders (CRON)
    - STRICTLY 1-BY-1 'Rellena-Huecos' cascade with timeout (zero double-booking risk)
    - Direct WhatsApp alerts to clinic owners and doctors
    """

    @staticmethod
    def create_appointment(
        db: Session,
        tenant_id: int,
        patient_name: str,
        patient_phone: str,
        doctor_or_service: str,
        appointment_date: datetime,
        notes: Optional[str] = None
    ) -> Appointment:
        clean_phone = "".join(filter(str.isdigit, patient_phone))
        apt = Appointment(
            tenant_id=tenant_id,
            patient_name=patient_name.strip(),
            patient_phone=clean_phone,
            doctor_or_service=doctor_or_service.strip(),
            appointment_date=appointment_date,
            status="agendado",
            notes=notes
        )
        db.add(apt)
        db.commit()
        db.refresh(apt)
        return apt

    @staticmethod
    def add_to_waitlist(
        db: Session,
        tenant_id: int,
        patient_name: str,
        patient_phone: str,
        doctor_or_service: str,
        preferred_time_range: Optional[str] = None
    ) -> WaitlistEntry:
        clean_phone = "".join(filter(str.isdigit, patient_phone))
        entry = WaitlistEntry(
            tenant_id=tenant_id,
            patient_name=patient_name.strip(),
            patient_phone=clean_phone,
            doctor_or_service=doctor_or_service.strip(),
            preferred_time_range=preferred_time_range or "Cualquier horario disponible",
            status="activa"
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    @staticmethod
    async def confirm_appointment(db: Session, appointment_id: int, sender_phone: Optional[str] = None) -> bool:
        apt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not apt:
            return False

        # Cerrojo: Si el turno ya fue cubierto por alguien de la lista de espera
        if apt.status == "rellenado_con_exito":
            if apt.tenant:
                date_str = format_appointment_datetime(apt.appointment_date)
                msg = (
                    f"⚠️ Hola! Te informamos que al haber pasado el horario límite de confirmación (18:00 hs), "
                    f"el turno del *{date_str}* ya fue asignado a otro paciente en lista de espera.\n\n"
                    f"Si deseás agendar una nueva fecha, escribinos por este medio y te buscamos lugar enseguida. 🙌"
                )
                target_phone = sender_phone or apt.patient_phone
                if target_phone:
                    await tenant_service.send_branded_notification(apt.tenant, target_phone, msg)
            return False

        # Si el turno estaba 'en_oferta_lista_espera' o 'cancelado' pero NADIE de la lista lo tomó aún,
        # el paciente titular que confirma tarde GANA el turno (Cero Sillas Vacías)
        # y anulamos cualquier oferta abierta en la lista de espera para este turno.
        active_offers = db.query(WaitlistEntry).filter(
            WaitlistEntry.offered_appointment_id == apt.id,
            WaitlistEntry.status == "notificado_oferta"
        ).all()
        for off in active_offers:
            off.status = "activa"  # Vuelve a estar activo en fila para el próximo hueco
            off.offered_appointment_id = None
            off.expires_at = None

        apt.status = "confirmado"
        apt.confirmation_received_at = utc_now()
        db.commit()

        # Send confirmation acknowledgment to patient
        if apt.tenant:
            date_str = format_appointment_datetime(apt.appointment_date)
            msg = (
                f"✅ *¡Turno confirmado con éxito!*\n\n"
                f"👤 Paciente: *{apt.patient_name}*\n"
                f"👨‍⚕️ Profesional: *{apt.doctor_or_service}*\n"
                f"📅 Fecha: *{date_str}*\n\n"
                f"¡Te esperamos puntual! Ante cualquier duda o imprevisto, avisanos por este medio."
            )
            await tenant_service.send_branded_notification(apt.tenant, apt.patient_phone, msg)
        return True

    @staticmethod
    async def offer_slot_to_next_candidate(
        db: Session,
        appointment_id: int,
        timeout_minutes: int = 120
    ) -> Optional[WaitlistEntry]:
        """
        STRICTLY 1-BY-1 CASCADE:
        Offers the liberated appointment to ONLY the next single candidate in line.
        Prevents multiple patients from accepting simultaneously.
        Gives a generous 2-hour window (120 minutes) for the candidate to respond.
        """
        apt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not apt or apt.status in ("rellenado_con_exito", "confirmado"):
            return None

        tenant = apt.tenant
        date_str = format_appointment_datetime(apt.appointment_date)

        # Query next candidate (FIFO: oldest registered first)
        next_cand = db.query(WaitlistEntry).filter(
            WaitlistEntry.tenant_id == tenant.id,
            WaitlistEntry.status == "activa"
        ).order_by(WaitlistEntry.id.asc()).first()

        if not next_cand:
            logger.info(f"ℹ️ No active waitlist candidates for slot #{appointment_id} ({date_str}). Attempting 'Adelanta-Turnos' Fast-Track...")
            # Fallback to Adelanta-Turnos (Fast-Track) for future patients
            fast_track_cand = await AppointmentService.offer_slot_via_fast_track(db, apt.id, timeout_minutes=timeout_minutes)
            if fast_track_cand:
                return fast_track_cand

            logger.info(f"ℹ️ No more candidates (waitlist or future) for slot #{appointment_id} ({date_str})")
            if tenant and tenant.owner_phone:
                await whatsapp.send_whatsapp_message(
                    tenant.owner_phone,
                    f"ℹ️ *Aviso Turno Libre:* Se liberó el turno del {date_str} ({apt.doctor_or_service}). No hay pacientes en lista de espera ni turnos futuros para adelantar. Queda disponible (o a la espera de que el paciente original confirme tarde)."
                )
            return None

        # Lock offer to this candidate with timeout (default 2 hours)
        now = utc_now()
        next_cand.status = "notificado_oferta"
        next_cand.offered_appointment_id = apt.id
        next_cand.offered_at = now
        next_cand.expires_at = now + timedelta(minutes=timeout_minutes)
        db.commit()
        if tenant:
            tenant_service.set_active_session(db, next_cand.patient_phone, tenant.slug)

        time_desc = "2 horas" if timeout_minutes == 120 else f"{timeout_minutes} minutos"

        # Check if candidate also has a future scheduled appointment to mention in template {{6}}
        existing_future = db.query(Appointment).filter(
            Appointment.tenant_id == tenant.id,
            Appointment.patient_phone == next_cand.patient_phone,
            Appointment.status.in_(["agendado", "confirmado"]),
            Appointment.id != apt.id
        ).order_by(Appointment.appointment_date.asc()).first()
        current_booking_desc = (
            format_appointment_datetime(existing_future.appointment_date, include_day_name=True)
            if existing_future else "nuestra Lista de Espera Prioritaria"
        )

        # Split date_str ("18/10 a las 09:30 hs") into day and hour for adelanta_turno_v1 ({{3}} and {{4}})
        full_day_str = format_appointment_datetime(apt.appointment_date, include_day_name=True)
        if " a las " in full_day_str:
            tpl_day_part, tpl_hour_part = full_day_str.split(" a las ", 1)
            tpl_hour_part = tpl_hour_part.replace(" hs", "").strip()
        else:
            tpl_day_part, tpl_hour_part = date_str, "horario asignado"

        offer_text = (
            f"🔔 *¡HUECO LIBERADO DE TURNO! (Exclusivo para vos)*\n\n"
            f"Hola *{next_cand.patient_name}*, te escribimos de *{tenant.name}*.\n"
            f"Se acaba de liberar un turno para el día *{date_str}* con *{apt.doctor_or_service}*.\n\n"
            f"Como estás en lista de espera, tenés prioridad para tomarlo.\n"
            f"⏱️ Tenés *{time_desc}* para confirmar antes de ofrecerlo al siguiente en fila."
        )
        buttons = [
            {"id": f"claim_apt_{apt.id}_{next_cand.id}", "title": "TOMAR TURNO"},
            {"id": f"reject_apt_{apt.id}_{next_cand.id}", "title": "NO, PASO"}
        ]
        await whatsapp.send_whatsapp_interactive_buttons(
            to_phone=next_cand.patient_phone,
            body_text=tenant_service.format_branded_message(tenant, offer_text),
            buttons=buttons,
            header_text=f"🏥 {tenant.name[:30]}",
            template_name="adelanta_turno_v1",
            template_body_params=[
                next_cand.patient_name,
                tenant.name,
                tpl_day_part,
                tpl_hour_part,
                apt.doctor_or_service,
                current_booking_desc
            ]
        )

        logger.info(f"⚡ Rellena-Huecos 1-by-1: Slot {date_str} offered to '{next_cand.patient_name}' (Expires in {time_desc})")
        return next_cand

    @staticmethod
    async def cancel_and_fill_gap(
        db: Session,
        appointment_id: int,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Triggered when a patient cancels or says they cannot attend.
        1. Marks original appointment as 'cancelado'.
        2. Acknowledges patient cancellation politely.
        3. Alerts the clinic owner / doctor immediately.
        4. Triggers the STRICT 1-by-1 waitlist cascade.
        """
        apt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not apt:
            return {"status": "error", "message": "Turno no encontrado"}

        apt.status = "cancelado"
        db.commit()

        tenant = apt.tenant
        date_str = format_appointment_datetime(apt.appointment_date)

        # 1. Acknowledge cancellation to original patient
        cancel_msg = (
            f"Comprendido {apt.patient_name}. Tu turno del *{date_str}* con *{apt.doctor_or_service}* ha sido cancelado.\n"
            f"Cuando desees reprogramar, escribinos por acá y te buscamos una nueva fecha. ¡Muchas gracias por avisar!"
        )
        await tenant_service.send_branded_notification(tenant, apt.patient_phone, cancel_msg)

        # 2. Alert Clinic Owner / Doctor on WhatsApp
        if tenant and tenant.owner_phone:
            owner_alert = (
                f"⚠️ *AVISO DE CANCELACIÓN DE TURNO*\n\n"
                f"El paciente *{apt.patient_name}* canceló su turno del *{date_str}* ({apt.doctor_or_service}).\n"
                f"Motivo: {reason or 'Imprevisto personal'}.\n\n"
                f"🚀 *Sofía está activando la Lista de Espera de a 1 paciente para cubrir el hueco sin doble reserva.*"
            )
            await whatsapp.send_owner_or_admin_alert(
                to_phone=tenant.owner_phone,
                fallback_text=owner_alert,
                business_name=tenant.name,
                event_type="Cancelación de Turno",
                client_title=f"{apt.patient_name} (+{apt.patient_phone})",
                details_summary=f"Fecha: {date_str}. Motivo: {reason or 'Imprevisto personal'}.",
                owner_email=tenant.owner_email
            )

        # 3. Offer slot to candidate #1 in waitlist
        cand = await AppointmentService.offer_slot_to_next_candidate(db, apt.id)

        return {
            "status": "success",
            "cancelled_appointment_id": apt.id,
            "waitlist_pings_sent": 1 if cand else 0,
            "candidate_offered": cand.patient_name if cand else None,
            "slot": date_str
        }

    @staticmethod
    async def reject_waitlist_slot(db: Session, appointment_id: int, waitlist_id: int) -> bool:
        """
        Called when the offered candidate clicks 'NO, PASO' or declines.
        Marks them as 'rechazado' for this offer and IMMEDIATELY passes to candidate #2.
        """
        cand = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist_id).first()
        if cand:
            cand.status = "rechazado"
            db.commit()

            # Check if patient already has a future confirmed appointment
            existing_apt = db.query(Appointment).filter(
                Appointment.patient_phone == cand.patient_phone,
                Appointment.status == "agendado"
            ).order_by(Appointment.appointment_date.asc()).first()

            if existing_apt:
                e_date_str = format_appointment_datetime(existing_apt.appointment_date)
                msg = (
                    f"¡Dale, no te preocupes {cand.patient_name}! Entendido que este horario no te queda cómodo.\n\n"
                    f"Despreocupate que tu turno agendado del *{e_date_str}* sigue *100% firme y confirmado tal cual estaba*. ¡Nos vemos ese día! 🙌"
                )
            else:
                msg = (
                    f"¡Dale, no te preocupes {cand.patient_name}! Entendido que este horario no te queda cómodo.\n\n"
                    f"Despreocupate que tu lugar en nuestra lista de espera *se mantiene tal cual estaba*, con prioridad para cuando se libere la próxima vacante. ¡Te avisamos apenas surja otro hueco! 🙌"
                )

            if cand.tenant:
                await tenant_service.send_branded_notification(cand.tenant, cand.patient_phone, msg)

        # Immediately pass to next candidate!
        logger.info(f"⏩ Candidate #{waitlist_id} declined. Passing slot #{appointment_id} to next candidate in line...")
        await AppointmentService.offer_slot_to_next_candidate(db, appointment_id)
        return True

    @staticmethod
    async def claim_waitlist_slot(db: Session, appointment_id: int, waitlist_id: int) -> bool:
        """
        Called when a waitlist candidate clicks 'TOMAR TURNO'.
        Assigns the liberated appointment to them and marks waitlist entry as 'turno_tomado'.
        """
        apt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        cand = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist_id).first()

        if not apt or not cand:
            return False

        # 1. Cerrojo de turno ya ocupado / rellenado o confirmado por el titular antes de que respondieran
        if apt.status in ("rellenado_con_exito", "confirmado"):
            msg = (
                f"Hola *{cand.patient_name}*, el turno ya fue cubierto por otro paciente. "
                f"Despreocupate que te mantendremos con máxima prioridad en la lista de espera ante la próxima vacante. 🙌"
            )
            await tenant_service.send_branded_notification(apt.tenant, cand.patient_phone, msg)
            return False

        # 2. Cerrojo de paciente que previamente rechazó ('NO, PASO')
        if cand.status == "rechazado":
            msg = (
                f"Hola *{cand.patient_name}*, anteriormente seleccionaste que no podías en este horario "
                f"y el turno fue derivado al siguiente paciente en lista de espera.\n\n"
                f"¡Despreocupate que tu lugar con prioridad se mantiene firme para la próxima vacante! 🙌"
            )
            await tenant_service.send_branded_notification(apt.tenant, cand.patient_phone, msg)
            return False

        # 3. Cerrojo de ventana de prioridad expirada
        now = utc_now()
        exp_dt = cand.expires_at.replace(tzinfo=timezone.utc) if (cand.expires_at and cand.expires_at.tzinfo is None) else cand.expires_at
        if cand.status == "expirada" or (exp_dt and exp_dt <= now):
            cand.status = "expirada"
            db.commit()
            msg = (
                f"Hola *{cand.patient_name}*, la ventana de prioridad para confirmar este turno ha vencido "
                f"y fue ofrecido al siguiente paciente en fila.\n\n"
                f"¡Despreocupate que seguís en nuestra lista de espera para el próximo hueco que se libere! 🙌"
            )
            await tenant_service.send_branded_notification(apt.tenant, cand.patient_phone, msg)
            return False

        # 4. Cerrojo de oferta no activa
        if cand.status != "notificado_oferta":
            msg = (
                f"Hola *{cand.patient_name}*, esta opción de turno ya no está activa. "
                f"Seguís en nuestra lista de espera con prioridad para la próxima vacante. 🙌"
            )
            await tenant_service.send_branded_notification(apt.tenant, cand.patient_phone, msg)
            return False

        # Guardamos datos del titular original por si venía del corte de las 18:00 hs
        original_patient_name = apt.patient_name
        original_patient_phone = apt.patient_phone
        was_cutoff_offer = (apt.status == "en_oferta_lista_espera")

        # Assign slot
        apt.patient_name = cand.patient_name
        apt.patient_phone = cand.patient_phone
        apt.status = "rellenado_con_exito"
        apt.confirmation_received_at = utc_now()
        apt.notes = f"Original: {original_patient_name} ({original_patient_phone})"
        cand.status = "turno_tomado"
        db.commit()

        date_str = format_appointment_datetime(apt.appointment_date)

        # Si venía del corte de las 18:00 hs, recién AHORA que otro paciente tomó el turno,
        # le avisamos al titular original que su turno fue reasignado por falta de confirmación.
        if was_cutoff_offer and original_patient_phone and original_patient_phone != cand.patient_phone:
            patient_notice = (
                f"⚠️ *AVISO OFICIAL DE TURNO LIBERADO POR FALTA DE CONFIRMACIÓN*\n\n"
                f"Hola *{original_patient_name}*, te informamos que al no haber recibido tu confirmación "
                f"antes del horario límite (18:00 hs), tu turno de mañana *{date_str}* con *{apt.doctor_or_service}* "
                f"ha sido *reasignado a un paciente en lista de espera*.\n\n"
                f"❌ *Por favor NO concurras al consultorio mañana*, ya que el horario fue otorgado a otra persona.\n\n"
                f"Si deseás solicitar un nuevo turno para otra fecha, respondé a este mensaje y te buscaremos lugar con gusto."
            )
            await tenant_service.send_branded_notification(apt.tenant, original_patient_phone, patient_notice)

        # Success notification to new patient
        success_msg = (
            f"🎉 *¡FELICITACIONES! TURNO ASIGNADO*\n\n"
            f"Hola {cand.patient_name}, el turno del *{date_str}* con *{apt.doctor_or_service}* "
            f"ha quedado confirmado a tu nombre en *{apt.tenant.name}*.\n\n"
            f"¡Te esperamos puntual!"
        )
        await tenant_service.send_branded_notification(apt.tenant, cand.patient_phone, success_msg, with_logo=True)

        # Notify clinic owner
        if apt.tenant and apt.tenant.owner_phone:
            owner_msg = (
                f"🎯 *¡HUECO CUBIERTO CON ÉXITO POR SOFÍA!*\n\n"
                f"El turno del *{date_str}* ({apt.doctor_or_service}) que se había liberado "
                f"fue reasignado exitosamente a *{cand.patient_name}* (Cel: +{cand.patient_phone}).\n\n"
                f"💰 *Cero pérdida de facturación para la clínica.*"
            )
            await whatsapp.send_owner_or_admin_alert(
                to_phone=apt.tenant.owner_phone,
                fallback_text=owner_msg,
                business_name=apt.tenant.name,
                event_type="Hueco Reasignado",
                client_title=f"{cand.patient_name} (+{cand.patient_phone})",
                details_summary=f"Turno {date_str} reasignado exitosamente.",
                owner_email=apt.tenant.owner_email
            )

        return True

    @staticmethod
    async def offer_slot_via_fast_track(
        db: Session,
        appointment_id: int,
        timeout_minutes: int = 120
    ) -> Optional[Appointment]:
        """
        ADELANTA-TURNOS (FAST-TRACK INTELIGENTE):
        When WaitlistEntry (FIFO) is empty, Sofia searches future appointments (between 2 and 14 days ahead)
        for the same doctor/service and offers them to move their appointment to this vacant earlier slot.
        """
        apt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not apt:
            return None

        tenant = apt.tenant
        now = utc_now()
        date_str = format_appointment_datetime(apt.appointment_date)

        # Find future patient with same doctor/service between 2 and 14 days ahead
        # excluding patients who already declined or expired in WaitlistEntry
        start_future = now + timedelta(days=2)
        end_future = now + timedelta(days=14)

        already_contacted_phones = [
            r[0] for r in db.query(WaitlistEntry.patient_phone).filter(
                WaitlistEntry.tenant_id == tenant.id,
                WaitlistEntry.status.in_(["rechazado", "expirada", "notificado_oferta", "turno_tomado"])
            ).all() if r[0]
        ]

        q_future = db.query(Appointment).filter(
            Appointment.tenant_id == tenant.id,
            Appointment.doctor_or_service == apt.doctor_or_service,
            Appointment.appointment_date >= start_future,
            Appointment.appointment_date <= end_future,
            Appointment.status.in_(["agendado", "confirmado"]),
            Appointment.id != apt.id
        )
        if already_contacted_phones:
            q_future = q_future.filter(~Appointment.patient_phone.in_(already_contacted_phones))

        future_apt = q_future.order_by(Appointment.appointment_date.asc()).first()

        if not future_apt:
            return None

        future_date_str = format_appointment_datetime(future_apt.appointment_date, include_day_name=True)
        time_desc = "2 horas" if timeout_minutes == 120 else f"{timeout_minutes} minutos"

        offer_text = (
            f"🌟 *¡OPORTUNIDAD EXCLUSIVA: ADELANTAR TU TURNO!*\n\n"
            f"Hola *{future_apt.patient_name}*, te escribimos de *{tenant.name}*.\n"
            f"Tenés turno agendado con *{apt.doctor_or_service}* para el *{future_date_str}*.\n\n"
            f"Se acaba de liberar un espacio para *MAÑANA ({date_str})*.\n"
            f"¿Te gustaría *adelantar tu consulta para mañana* y atenderte mucho antes sin esperar?\n\n"
            f"⏱️ Tenés *{time_desc}* para responder con tu preferencia:"
        )
        buttons = [
            {"id": f"fast_track_accept_{apt.id}_{future_apt.id}", "title": "SÍ, ADELANTAR"},
            {"id": f"fast_track_decline_{apt.id}_{future_apt.id}", "title": "NO, MANTENER FECHA"}
        ]
        full_day_str = format_appointment_datetime(apt.appointment_date, include_day_name=True)
        if " a las " in full_day_str:
            tpl_day_part, tpl_hour_part = full_day_str.split(" a las ", 1)
            tpl_hour_part = tpl_hour_part.replace(" hs", "").strip()
        else:
            tpl_day_part, tpl_hour_part = date_str, "horario asignado"

        await whatsapp.send_whatsapp_interactive_buttons(
            to_phone=future_apt.patient_phone,
            body_text=tenant_service.format_branded_message(tenant, offer_text),
            buttons=buttons,
            header_text=f"🏥 {tenant.name[:30]}",
            template_name="adelanta_turno_v1",
            template_body_params=[
                future_apt.patient_name,
                tenant.name,
                tpl_day_part,
                tpl_hour_part,
                apt.doctor_or_service,
                future_date_str
            ]
        )

        logger.info(f"🚀 Adelanta-Turnos: Vacant slot {date_str} offered to future patient '{future_apt.patient_name}' (Turno actual: {future_date_str})")
        return future_apt

    @staticmethod
    async def claim_fast_track_slot(db: Session, vacant_apt_id: int, future_apt_id: int) -> bool:
        """
        Called when a future patient clicks 'SÍ, ADELANTAR':
        1. Moves patient to vacant_apt and marks as 'rellenado_con_exito'.
        2. Marks old future_apt as 'liberado_por_adelanto' (freeing it up for new bookings).
        3. Confirms to patient and alerts clinic secretary.
        """
        vacant_apt = db.query(Appointment).filter(Appointment.id == vacant_apt_id).first()
        future_apt = db.query(Appointment).filter(Appointment.id == future_apt_id).first()
        if not vacant_apt or not future_apt:
            return False

        tenant = vacant_apt.tenant
        new_date_str = format_appointment_datetime(vacant_apt.appointment_date)
        old_date_str = format_appointment_datetime(future_apt.appointment_date)

        if vacant_apt.status in ("rellenado_con_exito", "confirmado"):
            msg = (
                f"Hola *{future_apt.patient_name}*, el turno de mañana ({new_date_str}) ya fue cubierto por otro paciente.\n\n"
                f"Despreocupate que tu turno original del *{old_date_str}* sigue *100% firme y confirmado*. ¡Nos vemos ese día! 🙌"
            )
            await tenant_service.send_branded_notification(tenant, future_apt.patient_phone, msg)
            return False

        now = utc_now()

        # 1. Update vacant slot with patient details
        vacant_apt.patient_name = future_apt.patient_name
        vacant_apt.patient_phone = future_apt.patient_phone
        vacant_apt.status = "rellenado_con_exito"
        vacant_apt.confirmation_received_at = now
        vacant_apt.notes = f"Adelantado desde turno original #{future_apt.id} ({old_date_str})"

        # 2. Free up future slot
        future_apt.status = "liberado_por_adelanto"
        future_apt.notes = f"Liberado porque paciente adelantó al #{vacant_apt.id} ({new_date_str})"
        db.commit()

        # 3. Confirmation to patient
        patient_ack = (
            f"🎉 *¡Turno adelantado con éxito!*\n\n"
            f"Hola *{vacant_apt.patient_name}*, tu turno con *{vacant_apt.doctor_or_service}* ha sido reprogramado para *MAÑANA ({new_date_str})*.\n\n"
            f"Tu turno anterior del {old_date_str} ha sido liberado. ¡Muchas gracias y te esperamos puntual!"
        )
        await tenant_service.send_branded_notification(tenant, vacant_apt.patient_phone, patient_ack)

        # 4. Alert secretary
        if tenant and tenant.owner_phone:
            owner_msg = (
                f"🎉 *¡ADELANTA-TURNOS EXITOSO!*\n\n"
                f"El paciente *{vacant_apt.patient_name}* aceptó adelantar su turno para *MAÑANA {new_date_str}* ({vacant_apt.doctor_or_service}).\n"
                f"📅 Su turno original del *{old_date_str}* quedó LIBRE en agenda para nuevos pacientes."
            )
            await whatsapp.send_owner_or_admin_alert(
                to_phone=tenant.owner_phone,
                fallback_text=owner_msg,
                business_name=tenant.name,
                event_type="Turno Adelantado Exitoso",
                client_title=f"{vacant_apt.patient_name}",
                details_summary=f"Adelantado a mañana {new_date_str}. Queda libre {old_date_str}.",
                owner_email=tenant.owner_email
            )

        logger.info(f"✅ Fast-track successful: {vacant_apt.patient_name} moved from {old_date_str} to {new_date_str}")
        return True

    @staticmethod
    async def reject_fast_track_slot(db: Session, vacant_apt_id: int, future_apt_id: int) -> bool:
        """
        Called when future patient clicks 'NO, MANTENER FECHA':
        Keeps their future appointment intact, sends confirmation, and notifies clinic staff.
        """
        future_apt = db.query(Appointment).filter(Appointment.id == future_apt_id).first()
        if future_apt and future_apt.tenant:
            date_str = format_appointment_datetime(future_apt.appointment_date)
            msg = (
                f"¡Dale, no te preocupes {future_apt.patient_name}! Entendido que preferís mantener tu fecha original.\n\n"
                f"Tu turno agendado del *{date_str}* sigue *100% firme y confirmado tal cual estaba*. ¡Nos vemos ese día! 🙌"
            )
            await tenant_service.send_branded_notification(future_apt.tenant, future_apt.patient_phone, msg)

        vacant_apt = db.query(Appointment).filter(Appointment.id == vacant_apt_id).first()
        if vacant_apt and vacant_apt.tenant and vacant_apt.tenant.owner_phone:
            v_date_str = format_appointment_datetime(vacant_apt.appointment_date)
            decline_msg = f"ℹ️ *Adelanta-Turnos:* El paciente futuro prefirió mantener su fecha. El turno de mañana {v_date_str} queda libre para sobreturnos."
            await whatsapp.send_owner_or_admin_alert(
                to_phone=vacant_apt.tenant.owner_phone,
                fallback_text=decline_msg,
                business_name=vacant_apt.tenant.name,
                event_type="Adelanta-Turnos Declinado",
                client_title="Paciente futuro",
                details_summary=f"Turno de mañana {v_date_str} queda disponible.",
                owner_email=vacant_apt.tenant.owner_email
            )
        return True

    @staticmethod
    async def scan_and_send_appointment_reminders(db: Session, hours_ahead: Optional[int] = None) -> Dict[str, int]:
        """
        DUAL-STAGE CRON (Dispatched in the morning from 08:00 hs Argentina):
        Stage 1: PASADO MAÑANA (2 calendar days ahead) -> First Reminder (only if booked >= 7 days in advance)
        Stage 2: MAÑANA (1 calendar day ahead, all slots from 07:00 AM to 23:00 hs) ->
                 - If booked < 36h before slot (very recent booking): auto-confirmed, no reminder needed.
                 - If booked >= 36h (48h+ before slot): sends interactive confirmation early in the morning
                   so patient has all day until 18:00 hs to confirm.
        Stage 3: Waitlist Timeout Sweeper -> Passes unresponded slots to candidate #2
        """
        now = utc_now()
        local_now = now - timedelta(hours=3)
        reminders_48h_sent = 0
        reminders_24h_sent = 0
        timeouts_processed = 0

        # -------------------------------------------------------------
        # STAGE 1: PASADO MAÑANA (Full calendar day 2 days ahead in Argentina)
        # Recordatorio natural y amable a la mañana, sin exigir confirmación aún
        # -------------------------------------------------------------
        start_48h = (local_now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_48h = (local_now + timedelta(days=2)).replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(hours=3)

        apts_48h = db.query(Appointment).filter(
            Appointment.status == "agendado",
            Appointment.reminder_48h_sent_at == None,
            Appointment.appointment_date >= start_48h,
            Appointment.appointment_date <= end_48h
        ).all()

        for apt in apts_48h:
            tenant = apt.tenant
            if not tenant:
                continue

            # Anti-Spam / Smart UX: Only send 48h heads-up if booked >= 7 days (168h) in advance.
            anticipation_hours = _get_booking_anticipation_hours(apt)
            if anticipation_hours is not None and anticipation_hours < 168.0:
                logger.info(
                    f"⏩ Skipping 48h reminder for '{apt.patient_name}' (Turno #{apt.id}): "
                    f"Booked with {anticipation_hours / 24.0:.1f} days anticipation (< 7 days). Will evaluate at 24h stage."
                )
                continue

            date_str = format_appointment_datetime(apt.appointment_date, include_day_name=True)
            body_text = (
                f"Hola *{apt.patient_name}*! Te recordamos con anticipación que faltan *2 días* para tu turno "
                f"el día *{date_str}* con *{apt.doctor_or_service}* en *{tenant.name}*.\n\n"
                f"¡Que tengas un excelente día! Mañana a primera hora te escribiremos para coordinar la confirmación."
            )

            # Natural text reminder (no aggressive buttons at 48h)
            sent = await tenant_service.send_branded_notification(tenant, apt.patient_phone, body_text)
            if sent:
                apt.reminder_48h_sent_at = now
                apt.reminder_sent_at = now
                apt.status = "recordatorio_48h"
                db.commit()
                reminders_48h_sent += 1

        # -------------------------------------------------------------
        # STAGE 2: MAÑANA (Full calendar day tomorrow in Argentina, from 7 AM to night)
        # Sent early in the morning regardless of slot hour so patient has until 18:00 hs!
        # -------------------------------------------------------------
        start_24h = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_24h = (local_now + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(hours=3)

        apts_24h = db.query(Appointment).filter(
            Appointment.status.in_(["agendado", "recordatorio_48h"]),
            Appointment.reminder_24h_sent_at == None,
            Appointment.appointment_date >= start_24h,
            Appointment.appointment_date <= end_24h
        ).all()

        for apt in apts_24h:
            tenant = apt.tenant
            if not tenant:
                continue

            # Regla "Es un RECORDATORIO": Si el paciente sacó el turno hace muy poquito (< 36 horas antes del turno,
            # ej: sacó turno ayer u hoy para mañana a las 7 AM / 8 AM / 18 hs), NO se va a olvidar porque lo acaba de pedir.
            # Lo damos por confirmado automáticamente y no lo molestamos con recordatorio.
            anticipation_hours = _get_booking_anticipation_hours(apt)
            if apt.status == "agendado" and anticipation_hours is not None and anticipation_hours < 36.0:
                apt.status = "confirmado"
                apt.confirmation_received_at = now
                db.commit()
                logger.info(
                    f"✅ Auto-confirming recent booking for '{apt.patient_name}' (Turno #{apt.id}): "
                    f"Booked {anticipation_hours:.1f}h before slot (< 36h). Skipping 24h reminder."
                )
                continue

            date_str = format_appointment_datetime(apt.appointment_date)
            full_day_str = format_appointment_datetime(apt.appointment_date, include_day_name=True)
            if " a las " in full_day_str:
                tpl_day_part, tpl_hour_part = full_day_str.split(" a las ", 1)
                tpl_hour_part = tpl_hour_part.replace(" hs", "").strip()
            else:
                tpl_day_part, tpl_hour_part = date_str, "horario asignado"

            clinic_address = "Consultorio Central"
            try:
                kb = json.loads(tenant.knowledge_base or "{}")
                if isinstance(kb, dict) and kb.get("direccion"):
                    clinic_address = str(kb["direccion"])
            except Exception:
                pass

            body_text = (
                f"Hola *{apt.patient_name}*! Te recordamos que *MAÑANA* es tu turno "
                f"el día *{date_str}* con *{apt.doctor_or_service}* en *{tenant.name}*.\n\n"
                f"⏰ Por favor confirmá tu asistencia antes de las *18:00 hs de hoy* para conservar tu lugar en agenda."
            )
            buttons = [
                {"id": f"confirm_apt_{apt.id}", "title": "SÍ, CONFIRMO"},
                {"id": f"cancel_apt_{apt.id}", "title": "NO, REPROGRAMAR"}
            ]

            sent = await whatsapp.send_whatsapp_interactive_buttons(
                to_phone=apt.patient_phone,
                body_text=tenant_service.format_branded_message(tenant, body_text),
                buttons=buttons,
                header_text=f"🏥 {tenant.name[:30]}",
                template_name="recordatorio_turno_v2",
                template_body_params=[
                    apt.patient_name,
                    tenant.name,
                    f"Mañana {tpl_day_part}",
                    tpl_hour_part,
                    apt.doctor_or_service,
                    clinic_address
                ]
            )
            if sent:
                apt.reminder_24h_sent_at = now
                apt.reminder_sent_at = now
                apt.status = "recordatorio_24h"
                db.commit()
                reminders_24h_sent += 1

        # -------------------------------------------------------------
        # STAGE 3: WAITLIST TIMEOUT SWEEPER (1-BY-1 PASS)
        # -------------------------------------------------------------
        expired_offers = db.query(WaitlistEntry).filter(
            WaitlistEntry.status == "notificado_oferta",
            WaitlistEntry.expires_at != None,
            WaitlistEntry.expires_at <= now
        ).all()

        for exp in expired_offers:
            exp.status = "expirada"
            db.commit()
            apt_id = exp.offered_appointment_id
            if apt_id:
                logger.info(f"⌛ Offer expired for '{exp.patient_name}'. Passing slot #{apt_id} to next candidate...")
                await AppointmentService.offer_slot_to_next_candidate(db, apt_id)
                timeouts_processed += 1

        logger.info(
            f"📅 CRON Turnero Completado: {reminders_48h_sent} a 48hs | "
            f"{reminders_24h_sent} a 24hs | {timeouts_processed} timeouts pasados al siguiente."
        )

        return {
            "reminders_48h": reminders_48h_sent,
            "reminders_24h": reminders_24h_sent,
            "timeouts_processed": timeouts_processed
        }

    @staticmethod
    async def send_secretary_pre_cutoff_report(db: Session, tenant_id: int) -> bool:
        """
        ESCUDO PARA LA SECRETARIA (17:30 HS):
        Sends an executive summary of tomorrow's unconfirmed appointments to the clinic secretary.
        Gives the staff full authority to 'hold' friendly patients before auto-cutoff at 18:00 hs.
        """
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant or not tenant.owner_phone:
            return False

        now = utc_now()
        # Calculate tomorrow window in Argentina time (UTC-3) while also covering UTC naive dates
        local_now = now - timedelta(hours=3)
        start_tomorrow = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_tomorrow = (local_now + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(hours=3)

        candidates = db.query(Appointment).filter(
            Appointment.tenant_id == tenant.id,
            Appointment.status.in_(["agendado", "recordatorio_48h", "recordatorio_24h"]),
            Appointment.appointment_date >= start_tomorrow,
            Appointment.appointment_date <= end_tomorrow
        ).order_by(Appointment.appointment_date.asc()).all()

        unconfirmed = []
        for apt in candidates:
            anticipation_hours = _get_booking_anticipation_hours(apt)
            if apt.status == "agendado" and anticipation_hours is not None and anticipation_hours < 36.0:
                apt.status = "confirmado"
                apt.confirmation_received_at = now
                db.commit()
                continue
            unconfirmed.append(apt)

        if not unconfirmed:
            logger.info(f"✅ All appointments for tomorrow in '{tenant.name}' are confirmed! No secretary alert needed.")
            return True

        lines = []
        for i, apt in enumerate(unconfirmed, 1):
            t_str = format_appointment_datetime(apt.appointment_date)
            lines.append(f"{i}. 👤 *{apt.patient_name}* — {t_str} ({apt.doctor_or_service}) [ID: {apt.id}]")

        list_text = "\n".join(lines)
        report_msg = (
            f"📋 *REPORTE DE TURNOS SIN CONFIRMAR (Para Mañana)*\n\n"
            f"Hola! Aún quedan *{len(unconfirmed)} turnos* de mañana pendientes de confirmación:\n\n"
            f"{list_text}\n\n"
            f"⏰ *A las 18:00 hs* se activará la lista de espera para ofrecer estos lugares.\n\n"
            f"👉 *Control de la Secretaría:*\n"
            f"• Si querés proteger a alguno: *«mantener a [Nombre]»* o *«mantener #{unconfirmed[0].id}»*.\n"
            f"• Si querés proteger a todos: *«mantener todos»*.\n"
            f"• Si no respondés nada: a las 18:00 hs Sofía activa la lista de espera de a 1 paciente."
        )

        await whatsapp.send_owner_or_admin_alert(
            to_phone=tenant.owner_phone,
            fallback_text=report_msg,
            business_name=tenant.name,
            event_type="Reporte Turnos Mañana",
            client_title="Secretaría",
            details_summary=f"{len(unconfirmed)} turnos sin confirmar para mañana.",
            owner_email=tenant.owner_email
        )
        logger.info(f"🛡️ Escudo Secretaria: Report sent to {tenant.owner_phone} for '{tenant.name}' ({len(unconfirmed)} unconfirmed).")
        return True

    @staticmethod
    async def hold_appointment_by_secretary(db: Session, tenant_id: int, query_text: str) -> Optional[Appointment]:
        """
        Processes a secretary command to protect/hold an unconfirmed appointment from auto-cancellation.
        Example commands: 'mantener a María', 'mantener a Pérez', 'mantener #12'.
        """
        clean_q = query_text.lower().replace("mantener a", "").replace("mantener", "").strip()
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return None

        # Check by ID if starts with #
        target_apt = None
        if clean_q.startswith("#") and clean_q[1:].isdigit():
            apt_id = int(clean_q[1:])
            target_apt = db.query(Appointment).filter(Appointment.id == apt_id, Appointment.tenant_id == tenant_id).first()
        elif clean_q == "todos":
            now = utc_now()
            local_now = now - timedelta(hours=3)
            start_tomorrow = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_tomorrow = (local_now + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(hours=3)
            all_pending = db.query(Appointment).filter(
                Appointment.tenant_id == tenant.id,
                Appointment.status.in_(["agendado", "recordatorio_48h", "recordatorio_24h"]),
                Appointment.appointment_date >= start_tomorrow,
                Appointment.appointment_date <= end_tomorrow
            ).all()
            for a in all_pending:
                a.status = "mantenido_por_secretaria"
            db.commit()
            if tenant.owner_phone:
                await whatsapp.send_whatsapp_message(
                    tenant.owner_phone,
                    f"✅ *¡Entendido!* Se mantuvieron los {len(all_pending)} turnos de mañana. Ninguno será ofrecido a la lista de espera a las 18 hs."
                )
            return all_pending[0] if all_pending else None
        else:
            # Search by patient name
            target_apt = db.query(Appointment).filter(
                Appointment.tenant_id == tenant_id,
                Appointment.patient_name.ilike(f"%{clean_q}%")
            ).order_by(Appointment.id.desc()).first()

        if target_apt:
            target_apt.status = "mantenido_por_secretaria"
            db.commit()
            t_str = format_appointment_datetime(target_apt.appointment_date)
            if tenant.owner_phone:
                await whatsapp.send_whatsapp_message(
                    tenant.owner_phone,
                    f"✅ *¡Turno conservado!*\nEl turno de *{target_apt.patient_name}* ({t_str}) queda marcado como MANTENIDO por secretaría. No será liberado a las 18 hs."
                )
            return target_apt
        return None

    @staticmethod
    async def execute_cutoff_auto_cancellations(db: Session, tenant_id: int) -> int:
        """
        CUTOFF AT 18:00 HS ("CERO SILLAS VACÍAS" / EL PRIMERO QUE CONFIRMA SE LO QUEDA):
        1. Marks unconfirmed appointments for tomorrow as 'en_oferta_lista_espera'.
        2. Does NOT kick out the original patient prematurely; instead starts offering the slot
           1-by-1 to the waitlist.
        3. Whichever patient confirms first (either someone in the waitlist clicking TOMAR TURNO,
           or the original patient clicking SÍ, CONFIRMO late while the slot is still unclaimed)
           gets the appointment!
        """
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return 0

        now = utc_now()
        local_now = now - timedelta(hours=3)
        start_tomorrow = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_tomorrow = (local_now + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(hours=3)

        to_offer = db.query(Appointment).filter(
            Appointment.tenant_id == tenant.id,
            Appointment.status.in_(["agendado", "recordatorio_48h", "recordatorio_24h"]),
            Appointment.appointment_date >= start_tomorrow,
            Appointment.appointment_date <= end_tomorrow
        ).all()

        offered_count = 0
        for apt in to_offer:
            anticipation_hours = _get_booking_anticipation_hours(apt)
            if apt.status == "agendado" and anticipation_hours is not None and anticipation_hours < 36.0:
                apt.status = "confirmado"
                apt.confirmation_received_at = now
                db.commit()
                continue

            apt.status = "en_oferta_lista_espera"
            db.commit()

            # Trigger strictly 1-by-1 waitlist cascade with 2h timeout
            await AppointmentService.offer_slot_to_next_candidate(db, apt.id, timeout_minutes=120)
            offered_count += 1

        if offered_count > 0 and tenant.owner_phone:
            cutoff_alert = (
                f"🎯 *Corte de las 18:00 hs activado:* Se pusieron en oferta {offered_count} turnos de mañana aún sin confirmar "
                f"hacia la lista de espera (de a 1 paciente por vez). El primero que confirme (de la lista o el titular si responde antes que otro lo tome) se queda con el lugar."
            )
            await whatsapp.send_owner_or_admin_alert(
                to_phone=tenant.owner_phone,
                fallback_text=cutoff_alert,
                business_name=tenant.name,
                event_type="Corte 18:00 hs Ejecutado",
                client_title="Secretaría",
                details_summary=f"{offered_count} turnos abiertos a lista de espera.",
                owner_email=tenant.owner_email
            )

        logger.info(f"🏁 Cutoff executed for '{tenant.name}': {offered_count} appointments opened to waitlist cascade.")
        return offered_count

    @staticmethod
    async def broadcast_secretary_pre_cutoff_reports(
        db: Session,
        tenant_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Runs secretary pre-cutoff summary report at 17:30 hs across all healthcare tenants
        (or for a single tenant if specified).
        """
        query = db.query(Tenant).filter(Tenant.active == True)
        if tenant_id:
            query = query.filter(Tenant.id == tenant_id)
        else:
            query = query.filter(
                (Tenant.business_type.in_(["salud", "medicina", "estetica"])) |
                (Tenant.modules_enabled.like("%turnos%"))
            )
        tenants = query.all()
        sent_count = 0
        for t in tenants:
            if t.owner_phone:
                ok = await AppointmentService.send_secretary_pre_cutoff_report(db, t.id)
                if ok:
                    sent_count += 1
        return {"tenants_processed": len(tenants), "reports_sent": sent_count}

    @staticmethod
    async def execute_all_cutoff_auto_cancellations(
        db: Session,
        tenant_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes 18:00 hs cutoff across all healthcare tenants (or for a single tenant).
        Opens unconfirmed slots (unless kept by secretary) to the 1-by-1 waitlist cascade.
        """
        query = db.query(Tenant).filter(Tenant.active == True)
        if tenant_id:
            query = query.filter(Tenant.id == tenant_id)
        else:
            query = query.filter(
                (Tenant.business_type.in_(["salud", "medicina", "estetica"])) |
                (Tenant.modules_enabled.like("%turnos%"))
            )
        tenants = query.all()
        total_cancelled = 0
        for t in tenants:
            c = await AppointmentService.execute_cutoff_auto_cancellations(db, t.id)
            total_cancelled += c
        return {"tenants_processed": len(tenants), "appointments_cancelled": total_cancelled}

appointment_service = AppointmentService()

