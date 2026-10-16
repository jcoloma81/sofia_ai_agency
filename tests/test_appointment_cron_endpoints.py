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

