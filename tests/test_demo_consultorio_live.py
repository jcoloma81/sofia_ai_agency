import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from tests.conftest import TestingSessionLocal
from app.models.tenant import Tenant, Appointment, WaitlistEntry
from scripts.demo_consultorio_live import (
    get_or_create_demo_tenant,
    setup_demo_scenario,
    execute_cancellation_step,
    execute_claim_step,
    clean_demo_scenario,
    main
)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    yield session
    session.close()


@pytest.mark.asyncio
async def test_get_or_create_demo_tenant(db):
    # 1. Create fresh tenant
    tenant = get_or_create_demo_tenant(
        db=db,
        clinic_name="Clínica Santa Fe Test",
        doctor_name="Dr. Test Rossi",
        doctor_phone="5493434536447",
        doctor_email="rossi@santafetest.com",
        slug="demo_test_santa_fe",
        deep_link_keyword="Santa_Fe_Demo"
    )
    assert tenant.id is not None
    assert tenant.slug == "demo_test_santa_fe"
    assert tenant.name == "Clínica Santa Fe Test"
    assert tenant.owner_name == "Dr. Test Rossi"
    assert tenant.owner_email == "rossi@santafetest.com"
    assert tenant.business_type == "salud"

    # 2. Update existing tenant
    updated = get_or_create_demo_tenant(
        db=db,
        clinic_name="Clínica Santa Fe Actualizada",
        doctor_name="Dr. Rossi Actualizado",
        doctor_phone="5493434536447",
        doctor_email="rossi.new@santafetest.com",
        slug="demo_test_santa_fe",
        deep_link_keyword="Santa_Fe_Demo"
    )
    assert updated.id == tenant.id
    assert updated.name == "Clínica Santa Fe Actualizada"
    assert updated.owner_name == "Dr. Rossi Actualizado"
    assert updated.owner_email == "rossi.new@santafetest.com"


@pytest.mark.asyncio
async def test_setup_demo_scenario(db):
    tenant = get_or_create_demo_tenant(db=db, slug="demo_scenario_test")
    apt, wl = setup_demo_scenario(
        db=db,
        tenant_id=tenant.id,
        doctor_name="Dr. Pablo Rossi - Odontología",
        patient_name="Martín Gómez",
        patient_phone="5493431111111",
        waitlist_patient_name="Laura Benítez",
        waitlist_patient_phone="5493432222222"
    )

    assert apt.id is not None
    assert apt.tenant_id == tenant.id
    assert apt.patient_name == "Martín Gómez"
    assert apt.patient_phone == "5493431111111"
    assert apt.status == "agendado"

    assert wl.id is not None
    assert wl.tenant_id == tenant.id
    assert wl.patient_name == "Laura Benítez"
    assert wl.patient_phone == "5493432222222"
    assert wl.status == "activa"


@pytest.mark.asyncio
async def test_full_live_demo_flow_cancellation_and_claim(db):
    tenant = get_or_create_demo_tenant(db=db, slug="demo_full_flow_test")
    apt, wl = setup_demo_scenario(
        db=db,
        tenant_id=tenant.id,
        doctor_name="Dr. Rossi",
        patient_name="Martín Paciente",
        waitlist_patient_name="Laura Candidata"
    )

    # 1. Simulate Cancellation
    with patch("app.services.whatsapp.send_owner_or_admin_alert", new_callable=AsyncMock) as mock_alert, \
         patch("app.services.whatsapp.send_whatsapp_interactive_buttons", new_callable=AsyncMock) as mock_btn, \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg:

        res = await execute_cancellation_step(db, apt.id, reason="Imprevisto personal")

        assert res["status"] == "success"
        assert res["cancelled_appointment_id"] == apt.id
        assert res["waitlist_pings_sent"] == 1
        assert res["candidate_offered"] == "Laura Candidata"

        # Check DB states
        db.refresh(apt)
        db.refresh(wl)
        assert apt.status == "cancelado"
        assert wl.status == "notificado_oferta"
        assert wl.offered_appointment_id == apt.id

        # Verify WhatsApp and Meta alerts were triggered
        assert mock_alert.called
        assert mock_btn.called

    # 2. Simulate Claim (Laura accepts)
    with patch("app.services.whatsapp.send_owner_or_admin_alert", new_callable=AsyncMock) as mock_alert_claim, \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg_claim:

        success = await execute_claim_step(db, apt.id, wl.id)
        assert success is True

        db.refresh(apt)
        db.refresh(wl)
        assert apt.status == "rellenado_con_exito"
        assert apt.patient_name == "Laura Candidata"
        assert wl.status == "turno_tomado"

        # Verify doctor was alerted of rescued slot
        assert mock_alert_claim.called
        claim_call = mock_alert_claim.call_args[1]
        assert "Hueco Reasignado" in claim_call.get("event_type", "")


@pytest.mark.asyncio
async def test_clean_demo_scenario(db):
    tenant = get_or_create_demo_tenant(db=db, slug="demo_clean_test")
    apt, wl = setup_demo_scenario(db=db, tenant_id=tenant.id)

    assert db.query(Appointment).filter(Appointment.tenant_id == tenant.id).count() == 1
    assert db.query(WaitlistEntry).filter(WaitlistEntry.tenant_id == tenant.id).count() == 1

    clean_demo_scenario(db, tenant.id)

    assert db.query(Appointment).filter(Appointment.tenant_id == tenant.id).count() == 0
    assert db.query(WaitlistEntry).filter(WaitlistEntry.tenant_id == tenant.id).count() == 0


@pytest.mark.asyncio
async def test_cli_flags_non_interactive():
    # Test CLI setup, cancel, claim, clean via arguments without interactive prompt
    with patch("sys.argv", ["demo_consultorio_live.py", "--setup", "--non-interactive"]), \
         patch("app.database.SessionLocal", side_effect=TestingSessionLocal):
        await main()

    with patch("sys.argv", ["demo_consultorio_live.py", "--cancel", "--non-interactive"]), \
         patch("app.database.SessionLocal", side_effect=TestingSessionLocal), \
         patch("app.services.whatsapp.send_owner_or_admin_alert", new_callable=AsyncMock), \
         patch("app.services.whatsapp.send_whatsapp_interactive_buttons", new_callable=AsyncMock), \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock):
        await main()

    with patch("sys.argv", ["demo_consultorio_live.py", "--claim", "--non-interactive"]), \
         patch("app.database.SessionLocal", side_effect=TestingSessionLocal), \
         patch("app.services.whatsapp.send_owner_or_admin_alert", new_callable=AsyncMock), \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock):
        await main()

    with patch("sys.argv", ["demo_consultorio_live.py", "--clean", "--non-interactive"]), \
         patch("app.database.SessionLocal", side_effect=TestingSessionLocal):
        await main()
