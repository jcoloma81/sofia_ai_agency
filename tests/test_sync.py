import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from main import app
from app.models.tenant import Tenant, Appointment, WaitlistEntry, MembershipPayment, InactiveCustomer
from tests.conftest import TestingSessionLocal

@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    # Seed required tenants
    t1 = db.query(Tenant).filter(Tenant.slug == "clinica_test").first()
    if not t1:
        t1 = Tenant(
            slug="clinica_test",
            name="Clínica Test Odontología",
            business_type="salud",
            owner_phone="5493434536447",
            active=True
        )
        db.add(t1)

    t2 = db.query(Tenant).filter(Tenant.slug == "gym_test").first()
    if not t2:
        t2 = Tenant(
            slug="gym_test",
            name="Gym Test Fitness",
            business_type="gimnasio",
            owner_phone="5493434536447",
            active=True
        )
        db.add(t2)

    t3 = db.query(Tenant).filter(Tenant.slug == "taller_test").first()
    if not t3:
        t3 = Tenant(
            slug="taller_test",
            name="Taller Mecánico Test",
            business_type="taller",
            owner_phone="5493434536447",
            active=True
        )
        db.add(t3)

    db.commit()
    yield db
    db.close()

def test_sync_template_endpoint(db_session):
    client = TestClient(app)
    resp = client.get("/api/v1/sync/clinica_test/template")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["business_type"] == "salud"
    assert "fecha" in data["template"]["columns"]
    assert "adelanta_turno" in data["template"]["columns"]
    assert "estado" in data["template"]["columns"]

def test_sync_appointments_salud(db_session):
    client = TestClient(app)
    payload = {
        "source": "desktop_excel",
        "rows": [
            {
                "fecha": "20/10/2026",
                "hora": "15:30",
                "paciente": "Elena Ramos",
                "telefono": "3434123456",
                "profesional": "Dra. Silvina Gómez - Ortodoncia",
                "notas": "Control de brackets"
            }
        ]
    }
    resp = client.post("/api/v1/sync/clinica_test", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["created_count"] == 1

    # Verify in DB
    apt = db_session.query(Appointment).filter(Appointment.patient_name == "Elena Ramos").first()
    assert apt is not None
    assert apt.patient_phone == "5493434123456"
    assert apt.status == "agendado"

    # Test Idempotency: re-syncing the same row should update instead of creating a duplicate
    resp_re = client.post("/api/v1/sync/clinica_test", json=payload)
    assert resp_re.status_code == 200
    data_re = resp_re.json()
    assert data_re["created_count"] == 0
    assert data_re["updated_count"] == 1

def test_sync_salud_waitlist_and_excel_cancellation(db_session):
    client = TestClient(app)
    # 1. Sync a tomorrow appointment + a future patient who wants to advance ("adelanta_turno": "SI")
    payload = {
        "source": "desktop_excel",
        "rows": [
            {
                "fecha": "18/10/2026 00:00",  # Test Excel date formatting with trailing 00:00
                "hora": "10:00",
                "paciente": "Juan Titular",
                "telefono": "3434001122",
                "profesional": "Dr. García - Odontología",
                "adelanta_turno": "NO",
                "estado": "Agendado",
                "notas": "Limpieza dental"
            },
            {
                "fecha": "28/10/2026",
                "hora": "17:00",
                "paciente": "Sofía Espera",
                "telefono": "3434998877",
                "profesional": "Dr. García - Odontología",
                "adelanta_turno": "SI",
                "estado": "Agendado",
                "notas": "Prefiere por la mañana si se libera"
            }
        ]
    }
    resp = client.post("/api/v1/sync/clinica_test", json=payload)
    assert resp.status_code == 200
    assert resp.json()["created_count"] == 2

    # Check WaitlistEntry created for Sofía Espera
    wl = db_session.query(WaitlistEntry).filter(WaitlistEntry.patient_phone == "5493434998877").first()
    assert wl is not None
    assert wl.status == "activa"

    # 2. Secretary changes Juan Titular's Estado to "Cancelado" in Excel and saves
    payload["rows"][0]["estado"] = "Cancelado"
    resp_cancel = client.post("/api/v1/sync/clinica_test", json=payload)
    assert resp_cancel.status_code == 200

    db_session.expire_all()
    apt_juan = db_session.query(Appointment).filter(Appointment.patient_phone == "5493434001122").first()
    assert apt_juan.status == "cancelado"

    # Waitlist candidate Sofía Espera should have been automatically offered the slot!
    wl_after = db_session.query(WaitlistEntry).filter(WaitlistEntry.patient_phone == "5493434998877").first()
    assert wl_after.status == "notificado_oferta"
    assert wl_after.offered_appointment_id == apt_juan.id

def test_sync_memberships_gym(db_session):
    client = TestClient(app)
    payload = {
        "source": "google_sheets",
        "rows": [
            {
                "socio": "Lucas Pérez",
                "telefono": "5493434991122",
                "plan": "CrossFit Pase Libre",
                "vencimiento": "10/11/2026",
                "monto": 28000
            }
        ]
    }
    resp = client.post("/api/v1/sync/gym_test", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["created_count"] == 1

    mem = db_session.query(MembershipPayment).filter(MembershipPayment.member_name == "Lucas Pérez").first()
    assert mem is not None
    assert mem.amount == 28000.0
    assert mem.payment_status == "pendiente"

def test_sync_workshop_order_notification(db_session):
    client = TestClient(app)
    payload = {
        "source": "desktop_excel",
        "rows": [
            {
                "cliente": "Carlos Martínez",
                "telefono": "5493434778899",
                "vehiculo_orden": "Ford Ranger AB999CD",
                "estado": "listo_para_retirar",
                "monto_saldo": 35000
            }
        ]
    }
    resp = client.post("/api/v1/sync/taller_test", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["created_count"] == 1

    cust = db_session.query(InactiveCustomer).filter(InactiveCustomer.customer_name == "Carlos Martínez").first()
    assert cust is not None
    assert cust.status == "listo_para_retirar"
