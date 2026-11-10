import json
import pytest
from fastapi.testclient import TestClient

from main import app
from app.models.tenant import Tenant
from app.models.prospect import Prospect
from app.services.audio_onboarding import DEFAULT_PROMPT_STEP_1

client = TestClient(app)

def test_trigger_audio_onboarding_via_webhook(db):
    """Sending 'alta clínica' starts the 4-audio onboarding session."""
    test_phone = "5493434001122"
    # Clean previous records
    db.query(Prospect).filter(Prospect.phone == test_phone).delete()
    db.query(Tenant).filter(Tenant.owner_phone == test_phone).delete()
    db.commit()

    payload = {
        "phone": test_phone,
        "message": "Hola, quiero dar de alta mi consultorio médico"
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert res_data["action"] == "audio_onboarding_started"
    assert "Audio 1" in res_data["reply"]

    # Verify prospect record
    prospect = db.query(Prospect).filter(Prospect.phone == test_phone).first()
    assert prospect is not None
    assert prospect.campaign == "onboarding_audio"
    assert prospect.status == "in_progress"

def test_full_4_audio_onboarding_workflow(db):
    """Executes the full 4-audio sequence and verifies Tenant creation and knowledge base."""
    test_phone = "5493434998877"
    db.query(Prospect).filter(Prospect.phone == test_phone).delete()
    db.query(Tenant).filter(Tenant.owner_phone == test_phone).delete()
    db.commit()

    # 1. Trigger Start
    r0 = client.post("/webhook", json={"phone": test_phone, "message": "alta clínica"})
    assert r0.status_code == 200

    # 2. Audio/Step 1: Identity & City
    r1 = client.post("/webhook", json={
        "phone": test_phone,
        "message": "Somos Consultorios Odontológicos Paraná, el titular es el Dr. Carlos Ruiz y estamos en Paraná, Entre Ríos"
    })
    assert r1.status_code == 200
    assert r1.json()["action"] == "audio_onboarding_step_advanced"
    assert r1.json()["meta"]["step"] == 2

    # 3. Audio/Step 2: Team & Specialties
    r2 = client.post("/webhook", json={
        "phone": test_phone,
        "message": "Atiende el Dr. Carlos Ruiz en odontología general y recibimos OSDE y Particular"
    })
    assert r2.status_code == 200
    assert r2.json()["action"] == "audio_onboarding_step_advanced"
    assert r2.json()["meta"]["step"] == 3

    # 4. Audio/Step 3: Schedules & Duration
    r3 = client.post("/webhook", json={
        "phone": test_phone,
        "message": "Atendemos de Lunes a Viernes de 8:30 a 12:30 y de 16:00 a 20:00 con turnos de 30 minutos"
    })
    assert r3.status_code == 200
    assert r3.json()["action"] == "audio_onboarding_step_advanced"
    assert r3.json()["meta"]["step"] == 4

    # 5. Audio/Step 4: Fees & Finalization
    r4 = client.post("/webhook", json={
        "phone": test_phone,
        "message": "La consulta sale $18.000, no cobramos seña previa y si alguien tiene urgencia le damos sobreturno"
    })
    assert r4.status_code == 200
    res4 = r4.json()
    assert res4["action"] == "audio_onboarding_completed"
    assert "FELICITACIONES" in res4["reply"]
    assert res4["meta"]["is_complete"] is True

    # Verify Tenant in Database
    tenant = db.query(Tenant).filter(Tenant.owner_phone == test_phone).first()
    assert tenant is not None
    assert tenant.business_type == "salud"
    assert tenant.active is True
    assert "turnos_rellena_huecos" in tenant.modules_enabled
    assert "recordatorios" in tenant.modules_enabled

    # Verify Knowledge Base
    kb = json.loads(tenant.knowledge_base)
    assert "Paraná" in kb["business_name"]
    assert "Dr." in kb["owner_name"] or "Carlos" in kb["owner_name"]
    assert "30 min" in kb["appointment_duration"]
    assert kb["onboarding_channel"] == "whatsapp_audio"

    # Verify Prospect updated
    pros = db.query(Prospect).filter(Prospect.phone == test_phone).first()
    assert pros.status == "onboarded"
    assert pros.campaign == "client_onboarding"

def test_cancellation_flow(db):
    """User can cancel the audio onboarding anytime by saying 'cancelar'."""
    test_phone = "5493434665544"
    db.query(Prospect).filter(Prospect.phone == test_phone).delete()
    db.commit()

    # Trigger
    client.post("/webhook", json={"phone": test_phone, "message": "alta clínica"})
    # Cancel
    r_cancel = client.post("/webhook", json={"phone": test_phone, "message": "cancelar"})
    assert r_cancel.status_code == 200
    assert "cancelada" in r_cancel.json()["reply"].lower()

    pros = db.query(Prospect).filter(Prospect.phone == test_phone).first()
    assert pros.campaign == "ai_agency"

def test_api_audio_step_endpoint(db):
    """Direct POST to /api/onboarding/audio-step works for web recording or external testing."""
    test_phone = "5493434771122"
    db.query(Prospect).filter(Prospect.phone == test_phone).delete()
    db.commit()

    response = client.post("/api/onboarding/audio-step", data={
        "phone": test_phone,
        "text": "Somos Consultorios Santa Fe, titular Dra. Claudia Rossi"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["handled"] is True
    assert data["meta"]["step"] == 2
