import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_trigger_appointment_reminders_endpoint():
    """Verify POST /api/tenants/cron/run-appointment-reminders executes and returns structured stats."""
    mock_stats = {
        "reminders_48h": 2,
        "reminders_24h": 1,
        "timeouts_processed": 0
    }
    with patch("app.services.appointment_service.AppointmentService.scan_and_send_appointment_reminders", new_callable=AsyncMock) as mock_scan:
        mock_scan.return_value = mock_stats
        
        # Test without parameters
        response = client.post("/api/tenants/cron/run-appointment-reminders")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["results"] == mock_stats
        
        # Test with optional hours_ahead parameter (backward-compatibility check)
        response_param = client.post("/api/tenants/cron/run-appointment-reminders?hours_ahead=24")
        assert response_param.status_code == 200
        assert response_param.json()["status"] == "success"

def test_trigger_secretary_shield_endpoint():
    """Verify POST /api/tenants/cron/run-secretary-shield runs across health tenants."""
    mock_batch = {"tenants_processed": 3, "reports_sent": 2}
    with patch("app.services.appointment_service.AppointmentService.broadcast_secretary_pre_cutoff_reports", new_callable=AsyncMock) as mock_shield:
        mock_shield.return_value = mock_batch
        
        response = client.post("/api/tenants/cron/run-secretary-shield")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["results"]["tenants_processed"] == 3
        assert data["results"]["reports_sent"] == 2

def test_trigger_cutoff_cancellations_endpoint():
    """Verify POST /api/tenants/cron/run-cutoff-cancellations runs 18hs auto-cutoff cascade."""
    mock_cutoff = {"tenants_processed": 3, "appointments_cancelled": 1}
    with patch("app.services.appointment_service.AppointmentService.execute_all_cutoff_auto_cancellations", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_cutoff
        
        response = client.post("/api/tenants/cron/run-cutoff-cancellations")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["results"]["appointments_cancelled"] == 1


@pytest.mark.asyncio
async def test_cutoff_18hs_first_to_confirm_wins_and_timezone(db):
    """
    Tests the 'Zero Empty Chairs / First to Confirm Wins' rule after 18:00 hs cutoff:
    1. At 18:00 hs, unconfirmed appointment moves to 'en_oferta_lista_espera' and pings Waitlist #1 (without kicking out the titular yet).
    2. Case A: If titular confirms late BEFORE Waitlist #1 claims it -> Titular keeps the slot ('confirmado' with UTC-3 time) and Waitlist #1 offer is reset to 'activa'.
    3. Case B: If Waitlist #1 claims it first -> Slot becomes 'rellenado_con_exito', titular is notified NOT to attend, and if titular later clicks 'SÍ, CONFIRMO', they are blocked by the lock.
    """
    from datetime import datetime, timezone, timedelta
    from app.models.tenant import Tenant, Appointment, WaitlistEntry
    from app.services.appointment_service import AppointmentService

    tenant = Tenant(
        slug="test_clinica_cutoff",
        name="Clínica Cutoff Test",
        business_type="salud",
        owner_phone="5493434000001",
        active=True
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    # Tomorrow at 22:00 UTC (which is 19:00 hs Argentina!)
    now = datetime.now(timezone.utc)
    local_now = now - timedelta(hours=3)
    tomorrow_19hs_arg_in_utc = (local_now + timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)

    apt1 = Appointment(
        tenant_id=tenant.id,
        patient_name="Javier Titular",
        patient_phone="5493434536447",
        doctor_or_service="Dr. González",
        appointment_date=tomorrow_19hs_arg_in_utc,
        status="recordatorio_24h"
    )
    wl1 = WaitlistEntry(
        tenant_id=tenant.id,
        patient_name="Martín Espera",
        patient_phone="5493435730520",
        doctor_or_service="Dr. González",
        status="activa"
    )
    db.add_all([apt1, wl1])
    db.commit()
    db.refresh(apt1)
    db.refresh(wl1)

    with patch("app.services.whatsapp.send_whatsapp_interactive_buttons", new_callable=AsyncMock) as mock_btns, \
         patch("app.services.tenant_service.TenantService.send_branded_notification", new_callable=AsyncMock) as mock_notify, \
         patch("app.services.whatsapp.send_owner_or_admin_alert", new_callable=AsyncMock):

        mock_btns.return_value = True
        mock_notify.return_value = True

        # 1. Execute 18:00 hs cutoff across all active healthcare tenants
        res_all = await AppointmentService.execute_all_cutoff_auto_cancellations(db, tenant_id=tenant.id)
        assert res_all["appointments_cancelled"] == 1
        db.refresh(apt1)
        db.refresh(wl1)
        assert apt1.status == "en_oferta_lista_espera"
        assert wl1.status == "notificado_oferta"
        assert wl1.offered_appointment_id == apt1.id
        # Original patient was NOT sent a cancellation notice yet!
        assert mock_notify.call_count == 0

        # 2. CASE A: Titular clicks 'SÍ, CONFIRMO' late ( e.g. 22:30 hs ) BEFORE Martín claims it!
        confirmed = await AppointmentService.confirm_appointment(db, apt1.id, sender_phone="5493434536447")
        assert confirmed is True
        db.refresh(apt1)
        db.refresh(wl1)
        assert apt1.status == "confirmado"
        # Waitlist candidate is returned to 'activa' for next slot
        assert wl1.status == "activa"
        assert wl1.offered_appointment_id is None

        # Verify confirmation message has 19:00 hs (Argentina UTC-3) instead of 22:00 hs (UTC)
        sent_msg = mock_notify.call_args[0][2]
        assert "19:00 hs" in sent_msg
        assert "22:00 hs" not in sent_msg

        # If Martín tries to click 'TOMAR TURNO' after Javier already confirmed, lock blocks him
        claimed_after = await AppointmentService.claim_waitlist_slot(db, apt1.id, wl1.id)
        assert claimed_after is False

        # 3. CASE B: Reset to 'en_oferta_lista_espera' and let Martín claim it FIRST
        apt1.status = "en_oferta_lista_espera"
        wl1.status = "notificado_oferta"
        wl1.offered_appointment_id = apt1.id
        wl1.expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
        db.commit()
        mock_notify.reset_mock()

        claimed_first = await AppointmentService.claim_waitlist_slot(db, apt1.id, wl1.id)
        assert claimed_first is True
        db.refresh(apt1)
        assert apt1.status == "rellenado_con_exito"
        assert apt1.patient_name == "Martín Espera"

        # Original patient (Javier) must now have received the official reassignment notice
        calls_phones = [c[0][1] for c in mock_notify.call_args_list]
        assert "5493434536447" in calls_phones

        # And if Javier later clicks 'SÍ, CONFIRMO', the lock blocks him and notifies him politely
        mock_notify.reset_mock()
        late_confirm = await AppointmentService.confirm_appointment(db, apt1.id, sender_phone="5493434536447")
        assert late_confirm is False
        assert mock_notify.call_count == 1
        assert "asignado a otro paciente en lista de espera" in mock_notify.call_args[0][2]


@pytest.mark.asyncio
async def test_morning_calendar_day_reminders_single_24h_for_all(db):
    """
    Tests the simplified Single 24h Reminder rule:
    1. ALL appointments scheduled for tomorrow receive the 24h interactive reminder with buttons.
    2. No 48h reminders are sent (reminders_48h == 0).
    3. Appointments for 2 days ahead (pasado mañana) wait until their 24h window.
    """
    from datetime import datetime, timezone, timedelta
    from app.models.tenant import Tenant, Appointment
    from app.services.appointment_service import AppointmentService

    tenant = Tenant(
        slug="test_clinica_morning_rem",
        name="Clínica Mañana Test",
        business_type="salud",
        owner_phone="5493434000002",
        active=True
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    now = datetime.now(timezone.utc)
    local_now = now - timedelta(hours=3)
    tomorrow_base = local_now + timedelta(days=1)
    day_after_base = local_now + timedelta(days=2)

    # A. Booking for tomorrow 07:00 AM Argentina (= 10:00 UTC)
    slot_7am_utc = tomorrow_base.replace(hour=10, minute=0, second=0, microsecond=0)
    apt_recent = Appointment(
        tenant_id=tenant.id,
        patient_name="Paciente Reciente 24h",
        patient_phone="5493434111111",
        doctor_or_service="Dr. González",
        appointment_date=slot_7am_utc,
        created_at=slot_7am_utc - timedelta(hours=20),
        status="agendado"
    )

    # B. Booked 3 days ago for tomorrow 07:00 AM Argentina (10:00 UTC)
    apt_7am_48h = Appointment(
        tenant_id=tenant.id,
        patient_name="Paciente 7AM (Sacó hace 3 días)",
        patient_phone="5493434222222",
        doctor_or_service="Dr. González",
        appointment_date=slot_7am_utc,
        created_at=slot_7am_utc - timedelta(days=3),
        status="agendado"
    )

    # C. Booked 4 days ago for tomorrow 19:00 hs Argentina (22:00 UTC)
    slot_19hs_utc = tomorrow_base.replace(hour=22, minute=0, second=0, microsecond=0)
    apt_19hs_48h = Appointment(
        tenant_id=tenant.id,
        patient_name="Paciente 19HS (Sacó hace 4 días)",
        patient_phone="5493434333333",
        doctor_or_service="Dr. González",
        appointment_date=slot_19hs_utc,
        created_at=slot_19hs_utc - timedelta(days=4),
        status="agendado"
    )

    # D. Booked 10 days ago for 2 days ahead (pasado mañana 18:00 hs Argentina = 21:00 UTC)
    slot_2days_utc = day_after_base.replace(hour=21, minute=0, second=0, microsecond=0)
    apt_2days_10d = Appointment(
        tenant_id=tenant.id,
        patient_name="Paciente 48h (Sacó hace 10 días)",
        patient_phone="5493434444444",
        doctor_or_service="Dr. González",
        appointment_date=slot_2days_utc,
        created_at=slot_2days_utc - timedelta(days=10),
        status="agendado"
    )

    db.add_all([apt_recent, apt_7am_48h, apt_19hs_48h, apt_2days_10d])
    db.commit()

    with patch("app.services.whatsapp.send_whatsapp_interactive_buttons", new_callable=AsyncMock) as mock_btns, \
         patch("app.services.tenant_service.TenantService.send_branded_notification", new_callable=AsyncMock) as mock_notify:

        mock_btns.return_value = True
        mock_notify.return_value = True

        stats = await AppointmentService.scan_and_send_appointment_reminders(db)

        db.refresh(apt_recent)
        db.refresh(apt_7am_48h)
        db.refresh(apt_19hs_48h)
        db.refresh(apt_2days_10d)

        # 1. All tomorrow appointments receive the single 24h interactive reminder!
        assert apt_recent.status == "recordatorio_24h"
        assert apt_7am_48h.status == "recordatorio_24h"
        assert apt_19hs_48h.status == "recordatorio_24h"
        assert stats["reminders_24h"] >= 3

        # 2. No 48h reminders are dispatched (reminders_48h == 0)
        assert apt_2days_10d.status == "agendado"
        assert stats["reminders_48h"] == 0


@pytest.mark.asyncio
async def test_appointment_resolution_ignores_past_and_alerts_secretary(db):
    """
    Tests that:
    1. A past zombie appointment (e.g. from 6 days ago) is IGNORED when confirming.
    2. An appointment in 'en_oferta_lista_espera' (or 'recordatorio_24h') for today/tomorrow is correctly matched.
    3. Secretaría (tenant.owner_phone) receives an immediate WhatsApp alert about the confirmed appointment.
    """
    from datetime import datetime, timezone, timedelta
    from app.models.tenant import Tenant, Appointment
    from app.services.tenant_dispatcher import TenantDispatcher

    tenant = Tenant(
        slug="test_clinica_past_shield",
        name="Clínica Alvear Test",
        business_type="salud",
        owner_phone="5493434536447",
        active=True
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    now = datetime.now(timezone.utc)
    phone = "5493435730520"

    # Past appointment from 6 days ago (Carlos Ruiz)
    apt_past = Appointment(
        tenant_id=tenant.id,
        patient_name="Carlos Ruiz",
        patient_phone=phone,
        doctor_or_service="Dr. García",
        appointment_date=now - timedelta(days=6),
        status="agendado"
    )

    # Current appointment today in cutoff (Martín Gómez)
    apt_today = Appointment(
        tenant_id=tenant.id,
        patient_name="Martín Gómez",
        patient_phone=phone,
        doctor_or_service="Dr. García",
        appointment_date=now + timedelta(hours=4),
        status="en_oferta_lista_espera"
    )

    db.add_all([apt_past, apt_today])
    db.commit()

    with patch("app.services.tenant_service.TenantService.send_branded_notification", new_callable=AsyncMock) as mock_patient_notify, \
         patch("app.services.whatsapp.send_owner_or_admin_alert", new_callable=AsyncMock) as mock_secretary_alert:

        mock_patient_notify.return_value = True
        mock_secretary_alert.return_value = True

        handled, reply = await TenantDispatcher.process_tenant_message(
            db=db,
            tenant=tenant,
            phone=phone,
            message="Confirmo asistencia"
        )

        assert handled is True
        db.refresh(apt_past)
        db.refresh(apt_today)

        # 1. Past appointment remained untouched!
        assert apt_past.status == "agendado"

        # 2. Today's appointment was confirmed for Martín Gómez (NOT Carlos Ruiz)!
        assert apt_today.status == "confirmado"

        # 3. Patient received confirmation with Martín Gómez
        assert mock_patient_notify.call_count == 1
        assert "Martín Gómez" in mock_patient_notify.call_args[0][2]

        # 4. Secretary received immediate alert on owner_phone!
        assert mock_secretary_alert.call_count == 1
        sec_call_args = mock_secretary_alert.call_args[1]
        assert sec_call_args["to_phone"] == "5493434536447"
        assert "Martín Gómez" in sec_call_args["fallback_text"]
        assert sec_call_args["event_type"] == "Turno Rescatado Post-Corte"


@pytest.mark.asyncio
async def test_natural_text_decline_and_claim_intents(db):
    """
    Tests Punto 1:
    - Patient typing 'quiero mantener el turno' (or 'mantengo') triggers waitlist decline / pass to candidate #2.
    - Patient typing 'si quiero el turno' (or 'lo tomo') claims the offer.
    """
    from datetime import datetime, timezone, timedelta
    from app.models.tenant import Tenant, Appointment, WaitlistEntry
    from app.services.tenant_dispatcher import TenantDispatcher

    tenant = Tenant(
        slug="test_clinica_natural_lang",
        name="Clínica Lenguaje Natural",
        business_type="salud",
        owner_phone="5493434000099",
        active=True
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    now = datetime.now(timezone.utc)
    phone_cand1 = "5493435111111"
    phone_cand2 = "5493435222222"

    apt_vacant = Appointment(
        tenant_id=tenant.id,
        patient_name="Vacante",
        patient_phone="5493435000000",
        doctor_or_service="Dr. Gómez",
        appointment_date=now + timedelta(days=1),
        status="en_oferta_lista_espera"
    )
    wl1 = WaitlistEntry(
        tenant_id=tenant.id,
        patient_name="Candidato Uno",
        patient_phone=phone_cand1,
        doctor_or_service="Dr. Gómez",
        status="notificado_oferta"
    )
    wl2 = WaitlistEntry(
        tenant_id=tenant.id,
        patient_name="Candidato Dos",
        patient_phone=phone_cand2,
        doctor_or_service="Dr. Gómez",
        status="activa"
    )
    db.add_all([apt_vacant, wl1, wl2])
    db.commit()
    db.refresh(apt_vacant)
    db.refresh(wl1)
    db.refresh(wl2)

    wl1.offered_appointment_id = apt_vacant.id
    db.commit()

    with patch("app.services.tenant_service.TenantService.send_branded_notification", new_callable=AsyncMock) as mock_notify, \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_interactive_buttons", new_callable=AsyncMock) as mock_btns, \
         patch("app.services.whatsapp.send_owner_or_admin_alert", new_callable=AsyncMock):

        mock_notify.return_value = True
        mock_msg.return_value = True
        mock_btns.return_value = True

        # 1. Candidato 1 types: "quiero mantener el turno" (natural text instead of button)
        handled, reply = await TenantDispatcher.process_tenant_message(
            db=db,
            tenant=tenant,
            phone=phone_cand1,
            message="quiero mantener el turno"
        )
        assert handled is True
        db.refresh(wl1)
        db.refresh(wl2)

        # Candidato 1 was rejected and slot passed to Candidato 2!
        assert wl1.status == "rechazado"
        assert wl2.status == "notificado_oferta"
        assert wl2.offered_appointment_id == apt_vacant.id

        # 2. Candidato 2 types: "si quiero el turno"
        handled2, reply2 = await TenantDispatcher.process_tenant_message(
            db=db,
            tenant=tenant,
            phone=phone_cand2,
            message="si quiero el turno"
        )
        assert handled2 is True
        db.refresh(wl2)
        db.refresh(apt_vacant)

        # Slot claimed!
        assert wl2.status == "turno_tomado"
        assert apt_vacant.status == "rellenado_con_exito"
        assert apt_vacant.patient_name == "Candidato Dos"


@pytest.mark.asyncio
async def test_secretary_kill_switch_pause_and_resume(db):
    """
    Tests Punto 3:
    - Secretary sends 'pausar sofia' -> tenant.is_paused becomes True.
    - Automated sweeps (reminders, cutoffs) skip paused tenants.
    - Secretary sends 'estado sofia' -> reports paused state.
    - Secretary sends 'activar sofia' -> tenant.is_paused becomes False.
    """
    from datetime import datetime, timezone, timedelta
    from app.models.tenant import Tenant, Appointment
    from app.services.tenant_dispatcher import TenantDispatcher
    from app.services.appointment_service import AppointmentService

    secretary_phone = "5493434999888"
    tenant = Tenant(
        slug="test_clinica_kill_switch",
        name="Clínica Escudo Test",
        business_type="salud",
        owner_phone=secretary_phone,
        active=True,
        is_paused=False
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    now = datetime.now(timezone.utc)
    local_now = now - timedelta(hours=3)
    tomorrow = (local_now + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)

    apt = Appointment(
        tenant_id=tenant.id,
        patient_name="Paciente Mañana",
        patient_phone="5493434123456",
        doctor_or_service="Dr. Gómez",
        appointment_date=tomorrow,
        status="agendado"
    )
    db.add(apt)
    db.commit()

    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_interactive_buttons", new_callable=AsyncMock) as mock_btns:

        mock_msg.return_value = True
        mock_btns.return_value = True

        # 1. Secretary sends 'pausar sofia'
        handled, reply = await TenantDispatcher.process_tenant_message(
            db=db,
            tenant=tenant,
            phone=secretary_phone,
            message="pausar sofia"
        )
        assert handled is True
        db.refresh(tenant)
        assert tenant.is_paused is True
        assert "SOFÍA PAUSADA" in reply

        # 2. While paused, reminders cron skips this tenant
        stats = await AppointmentService.scan_and_send_appointment_reminders(db)
        db.refresh(apt)
        assert apt.status == "agendado"  # NOT changed to recordatorio_24h!
        assert mock_btns.call_count == 0

        # 3. Secretary checks status: 'estado'
        handled_status, reply_status = await TenantDispatcher.process_tenant_message(
            db=db,
            tenant=tenant,
            phone=secretary_phone,
            message="estado"
        )
        assert handled_status is True
        assert "PAUSADA (Modo Manual)" in reply_status

        # 4. Secretary sends 'activar sofia'
        handled_act, reply_act = await TenantDispatcher.process_tenant_message(
            db=db,
            tenant=tenant,
            phone=secretary_phone,
            message="activar sofia"
        )
        assert handled_act is True
        db.refresh(tenant)
        assert tenant.is_paused is False
        assert "SOFÍA REACTIVADA" in reply_act




