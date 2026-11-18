import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from tests.conftest import TestingSessionLocal
from app.models.tenant import Tenant, Appointment, WaitlistEntry
from app.services.appointment_service import appointment_service
from app.services.tenant_dispatcher import tenant_dispatcher


@pytest.fixture
def db():
    session = TestingSessionLocal()
    yield session
    session.close()


@pytest.mark.asyncio
async def test_waitlist_offer_template_grammar_when_no_future_booking(db):
    """
    Validates that {{6}} parameter in 'adelanta_turno_v1' reads naturally
    ('que solicitaste en nuestra Lista de Espera') instead of 'nuestra Lista de Espera Prioritaria'.
    """
    tenant = Tenant(
        name="Consultorios Test Alvear",
        slug="test_alvear_grammar",
        owner_name="Dra. Silvina Gómez",
        owner_phone="5493439999999",
        business_type="salud",
        modules_enabled="turnos_rellena_huecos"
    )
    db.add(tenant)
    db.commit()

    now = datetime.now(timezone.utc)
    apt = Appointment(
        tenant_id=tenant.id,
        patient_name="Gustavo Martínez",
        patient_phone="5493431111111",
        doctor_or_service="Dr. Rossi - Ortodoncia",
        appointment_date=now + timedelta(days=1),
        status="en_oferta_lista_espera"
    )
    wl = WaitlistEntry(
        tenant_id=tenant.id,
        patient_name="Laura Benítez",
        patient_phone="5493432222222",
        doctor_or_service="Dr. Rossi - Ortodoncia",
        status="activa"
    )
    db.add_all([apt, wl])
    db.commit()

    with patch("app.services.whatsapp.send_whatsapp_interactive_buttons", new_callable=AsyncMock) as mock_send:
        cand = await appointment_service.offer_slot_to_next_candidate(db, apt.id)
        assert cand is not None
        assert cand.patient_name == "Laura Benítez"

        # Check template_body_params
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["template_name"] == "adelanta_turno_v1"
        body_params = call_kwargs["template_body_params"]
        # Parameter 6 is the booking description
        assert body_params[5] == "que solicitaste en nuestra Lista de Espera"


@pytest.mark.asyncio
async def test_reallocated_appointment_flow_and_late_confirmation(db):
    """
    Validates that when a cutoff appointment is claimed:
    1. A 'reasignado_por_falta_confirmacion' record is created for the original patient.
    2. Original patient is notified of liberation.
    3. Late confirmation intent from original patient receives the reallocated explanation.
    4. Reschedule intent from original patient receives assistance to coordinate a new date.
    5. Winning waitlist patient confirming receives their confirmation message.
    """
    tenant = Tenant(
        name="Consultorios Test Alvear 2",
        slug="test_alvear_late_confirm",
        owner_name="Dra. Silvina Gómez",
        owner_phone="5493438888888",
        business_type="salud",
        modules_enabled="turnos_rellena_huecos"
    )
    db.add(tenant)
    db.commit()

    now = datetime.now(timezone.utc)
    apt = Appointment(
        tenant_id=tenant.id,
        patient_name="Gustavo Martínez",
        patient_phone="5493431234567",
        doctor_or_service="Dr. Rossi - Ortodoncia",
        appointment_date=now + timedelta(days=1),
        status="en_oferta_lista_espera"
    )
    wl = WaitlistEntry(
        tenant_id=tenant.id,
        patient_name="Laura Benítez",
        patient_phone="5493437654321",
        doctor_or_service="Dr. Rossi - Ortodoncia",
        status="notificado_oferta",
        offered_appointment_id=apt.id,
        expires_at=now + timedelta(hours=2)
    )
    db.add_all([apt, wl])
    db.commit()

    # Laura claims slot
    with patch("app.services.tenant_service.tenant_service.send_branded_notification", new_callable=AsyncMock) as mock_brand, \
         patch("app.services.whatsapp.send_owner_or_admin_alert", new_callable=AsyncMock):
        claimed = await appointment_service.claim_waitlist_slot(db, apt.id, wl.id)
        assert claimed is True

        # Check that original patient was notified
        assert mock_brand.call_count >= 2
        notified_phones = [c.args[1] for c in mock_brand.call_args_list]
        assert "5493431234567" in notified_phones  # Gustavo
        assert "5493437654321" in notified_phones  # Laura

    # Check database records
    # 1. Slot is now Laura's
    updated_apt = db.query(Appointment).filter(Appointment.id == apt.id).first()
    assert updated_apt.patient_name == "Laura Benítez"
    assert updated_apt.status == "rellenado_con_exito"

    # 2. Historical reallocated record for Gustavo exists
    lost = db.query(Appointment).filter(
        Appointment.tenant_id == tenant.id,
        Appointment.patient_phone == "5493431234567",
        Appointment.status == "reasignado_por_falta_confirmacion"
    ).first()
    assert lost is not None
    assert lost.patient_name == "Gustavo Martínez"

    # 3. Gustavo sends late confirmation ("Confirmo asistencia")
    with patch("app.services.tenant_service.tenant_service.send_branded_notification", new_callable=AsyncMock) as mock_brand_reply:
        handled, reply = await tenant_dispatcher.process_tenant_message(
            db=db,
            tenant=tenant,
            phone="5493431234567",
            message="Hola Gustavo Martínez, confirmo asistencia"
        )
        assert handled is True
        assert "reasignado a un paciente en lista de espera" in reply
        assert "Por favor NO concurras al consultorio mañana" in reply

    # 4. Gustavo asks to reschedule ("Reprogramar")
    with patch("app.services.tenant_service.tenant_service.send_branded_notification", new_callable=AsyncMock) as mock_brand_reply:
        handled, reply = await tenant_dispatcher.process_tenant_message(
            db=db,
            tenant=tenant,
            phone="5493431234567",
            message="Reprogramar mi turno"
        )
        assert handled is True
        assert "ya había sido liberado tras el corte de las 18:00 hs" in reply
        assert "coordinar una nueva fecha" in reply

    # 5. Laura (current slot holder) confirms ("Confirmo asistencia")
    with patch("app.services.tenant_service.tenant_service.send_branded_notification", new_callable=AsyncMock) as mock_brand_reply:
        handled, reply = await tenant_dispatcher.process_tenant_message(
            db=db,
            tenant=tenant,
            phone="5493437654321",
            message="Confirmo asistencia"
        )
        assert handled is True
        assert reply == "Turno confirmado."
        mock_brand_reply.assert_called_once()
        sent_text = mock_brand_reply.call_args[0][2]
        assert "100% confirmado y reservado a tu nombre" in sent_text
