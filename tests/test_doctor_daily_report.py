import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from main import app
from app.models.tenant import Tenant, Appointment, WaitlistEntry
from app.services.appointment_service import appointment_service

client = TestClient(app)

@pytest.fixture
def doctor_report_tenant(db):
    """Creates a sample clinic with today's and tomorrow's appointments."""
    t = db.query(Tenant).filter(Tenant.slug == "clinica_report_demo").first()
    if not t:
        t = Tenant(
            slug="clinica_report_demo",
            name="Consultorios San Martín",
            business_type="salud",
            owner_phone="5493434556677",
            owner_name="Dr. Federico Rossi",
            active=True
        )
        db.add(t)
        db.commit()
        db.refresh(t)

    # Clean old appointments for this tenant
    db.query(Appointment).filter(Appointment.tenant_id == t.id).delete()
    db.commit()

    now_utc = datetime.now(timezone.utc)
    # Today appointment (confirmed)
    apt1 = Appointment(
        tenant_id=t.id,
        patient_name="Ana Benítez",
        patient_phone="5493434111111",
        doctor_or_service="Dr. Rossi",
        appointment_date=now_utc,
        status="confirmado",
        notes="Control anual"
    )
    # Today appointment (gap rescued)
    apt2 = Appointment(
        tenant_id=t.id,
        patient_name="Carlos Méndez",
        patient_phone="5493434222222",
        doctor_or_service="Dr. Rossi",
        appointment_date=now_utc,
        status="rellenado_con_exito",
        notes="Rescatado de lista de espera"
    )
    # Tomorrow appointment
    apt3 = Appointment(
        tenant_id=t.id,
        patient_name="Valeria Fontana",
        patient_phone="5493434333333",
        doctor_or_service="Dr. Rossi",
        appointment_date=now_utc + timedelta(days=1),
        status="agendado",
        notes="Primera consulta"
    )
    db.add_all([apt1, apt2, apt3])

    # Waitlist candidate
    wl = WaitlistEntry(
        tenant_id=t.id,
        patient_name="Lucas Pereyra",
        patient_phone="5493434444444",
        doctor_or_service="Dr. Rossi",
        status="activa"
    )
    db.add(wl)
    db.commit()

    return t

@pytest.mark.asyncio
async def test_send_doctor_daily_closing_report(db, doctor_report_tenant):
    """Verifies that the daily closing report calculates metrics and dispatches WhatsApp alert."""
    ok = await appointment_service.send_doctor_daily_closing_report(db, doctor_report_tenant.id)
    assert ok is True

def test_cron_endpoint_daily_doctor_report(doctor_report_tenant):
    """Verifies POST /api/tenants/cron/run-daily-doctor-report triggers successfully."""
    response = client.post(f"/api/tenants/cron/run-daily-doctor-report?tenant_id={doctor_report_tenant.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["results"]["tenants_processed"] == 1
    assert data["results"]["reports_sent"] == 1
