import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from main import app
from app.database import get_db
from app.models.prospect import Prospect
from app.config.settings import settings
from tests.conftest import TestingSessionLocal

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.query(Prospect).delete()
        session.commit()
        session.close()

@pytest.fixture
def mock_whatsapp():
    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("app.services.whatsapp.notify_owner_order_confirmed", new_callable=AsyncMock) as mock_order_alert, \
         patch("app.services.whatsapp.notify_javier_meeting_scheduled", new_callable=AsyncMock) as mock_meeting_alert:
        mock_send.return_value = True
        yield mock_send, mock_order_alert, mock_meeting_alert

def test_distributor_price_inquiry(db, mock_whatsapp):
    mock_send, _, _ = mock_whatsapp

    payload = {
        "phone": "5493434112233",
        "message": "Hola, ¿a cuánto tenés el aceite cañuelas?",
        "complex_name": "Almacén Don Carlos",
        "contact_name": "Carlos",
        "city": "Paraná"
    }

    res = client.post("/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data.get("price_quote") is True
    assert "$14.400" in data["reply"]
    assert "Aceite Cañuelas 1.5L" in data["reply"]
    mock_send.assert_awaited()

def test_distributor_order_and_confirmation_flow(db, mock_whatsapp):
    mock_send, mock_order_alert, _ = mock_whatsapp

    # 1. Customer places an order: 3 oils ($14.400 c/u = $43.200) and 2 flours ($12.500 c/u = $25.000)
    order_payload = {
        "phone": "5493434223344",
        "message": "Mandame 3 cajas de aceite y 2 fardos de harina",
        "complex_name": "Autoservicio San Martín",
        "contact_name": "Martín",
        "city": "Paraná"
    }

    res_order = client.post("/webhook", json=order_payload)
    assert res_order.status_code == 200
    data_order = res_order.json()
    assert data_order["status"] == "success"
    assert data_order.get("order_draft") is True
    assert "$68.200" in data_order["reply"]
    assert "3x Aceite" in data_order["reply"]
    assert "2x Harina" in data_order["reply"]

    # Verify prospect in DB has pending order in notes
    prospect = db.query(Prospect).filter(Prospect.phone == "5493434223344").first()
    assert prospect is not None
    assert "PEDIDO_PENDIENTE" in prospect.notes

    # 2. Customer confirms order: "Sí dale, confirmalo"
    confirm_payload = {
        "phone": "5493434223344",
        "message": "Sí dale, confirmalo para mañana"
    }

    res_confirm = client.post("/webhook", json=confirm_payload)
    assert res_confirm.status_code == 200
    data_confirm = res_confirm.json()
    assert data_confirm["status"] == "success"
    assert data_confirm.get("order_confirmed") is True
    assert "depósito" in data_confirm["reply"].lower()

    # Verify prospect status in DB is order_confirmed
    db.refresh(prospect)
    assert prospect.status == "order_confirmed"
    assert "$68.200" in prospect.meeting_details

    # Verify instant alert sent to Owner/Depot
    mock_order_alert.assert_awaited_once()
    call_kwargs = mock_order_alert.call_args.kwargs
    assert call_kwargs["client_name"] == "Autoservicio San Martín"
    assert call_kwargs["phone"] == "5493434223344"
    assert call_kwargs["order_draft"].formatted_total() == "$68.200"

def test_boss_mode_full_controls(db, mock_whatsapp):
    mock_send, _, _ = mock_whatsapp
    boss_phone = settings.WHATSAPP_ALERT_PHONE

    # 1. Ask for metrics
    res_metrics = client.post("/webhook", json={
        "phone": boss_phone,
        "message": "resumen de ventas y estado"
    })
    assert res_metrics.status_code == 200
    assert res_metrics.json()["action"] == "boss_metrics"
    assert "REPORTE EJECUTIVO" in res_metrics.json()["reply"]

    # 2. Pause a customer chat
    client.post("/webhook", json={
        "phone": "5493434887766",
        "message": "Hola, ¿a cuánto tenés el arroz?",
        "complex_name": "Kiosco El Paso"
    })

    res_pause = client.post("/webhook", json={
        "phone": boss_phone,
        "message": "pausar 4887766"
    })
    assert res_pause.status_code == 200
    assert res_pause.json()["action"] == "human_takeover_set"
    assert "silenciada" in res_pause.json()["reply"]

    lead = db.query(Prospect).filter(Prospect.phone == "5493434887766").first()
    assert lead.status == "human_takeover"

    # 3. Reactivate customer chat
    res_reactivate = client.post("/webhook", json={
        "phone": boss_phone,
        "message": "activar 4887766"
    })
    assert res_reactivate.status_code == 200
    assert res_reactivate.json()["action"] == "lead_reactivated"

    db.refresh(lead)
    assert lead.status == "in_conversation"

    # 4. Test 6-hour auto-reactivation
    lead.status = "human_takeover"
    lead.updated_at = datetime.now(timezone.utc) - timedelta(hours=6.5)
    db.commit()

    res_after_6h = client.post("/webhook", json={
        "phone": "5493434887766",
        "message": "¿Sigue disponible el arroz?",
        "complex_name": "Kiosco El Paso"
    })
    assert res_after_6h.status_code == 200
    db.refresh(lead)
    assert lead.status == "in_conversation"

