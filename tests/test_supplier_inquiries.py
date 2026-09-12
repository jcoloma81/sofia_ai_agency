import pytest
import json
import asyncio
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from main import app
from app.config.settings import settings
from app.database import Base, get_db
from app.models.prospect import Prospect
from tests.conftest import test_engine, TestingSessionLocal
from app.services.boss_mode import (
    process_boss_message,
    get_client_faq_text,
    get_client_manual_text,
    parse_supplier_inquiry_intent
)

Base.metadata.create_all(bind=test_engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

@pytest.fixture
def mock_whatsapp():
    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tpl, \
         patch("app.services.whatsapp.notify_javier_meeting_scheduled", new_callable=AsyncMock) as mock_alert:
        mock_msg.return_value = True
        mock_tpl.return_value = True
        yield mock_msg, mock_tpl, mock_alert


@pytest.mark.asyncio
async def test_parse_supplier_inquiry_intent():
    # 1. Standard question
    r1 = await parse_supplier_inquiry_intent("Sofi, preguntale a Pedro de Distribuidora Alem si el lunes hacen reparto")
    assert r1.get("is_supplier_inquiry") is True
    assert "Pedro" in r1.get("supplier_name", "") or "Distribuidora Alem" in r1.get("supplier_name", "")
    assert "lunes hacen reparto" in r1.get("inquiry_text", "")

    # 2. Consultale a
    r2 = await parse_supplier_inquiry_intent("consultale a Distribuidora Central por qué no llegó el camión")
    assert r2.get("is_supplier_inquiry") is True
    assert "Distribuidora Central" in r2.get("supplier_name", "")

    # 3. Decile a
    r3 = await parse_supplier_inquiry_intent("decile a Pedro que me guarde 5 cajas de alfajores")
    assert r3.get("is_supplier_inquiry") is True
    assert "Pedro" in r3.get("supplier_name", "")

    # 4. Non-inquiry (e.g. order dispatch)
    r4 = await parse_supplier_inquiry_intent("Sofi, mandale el pedido a Distribuidora Alem")
    assert r4.get("is_supplier_inquiry") is False

    # 5. Incomplete prompt
    r5 = await parse_supplier_inquiry_intent("Sofi, preguntale a")
    assert r5.get("is_supplier_inquiry") is True
    assert r5.get("inquiry_text") is None


@pytest.mark.asyncio
async def test_merchant_direct_inquiry_outbound_dispatch(db, mock_whatsapp):
    mock_msg, mock_tpl, _ = mock_whatsapp

    sup_phone = "5493434666555"

    # Register supplier for boss
    sup = Prospect(
        phone=sup_phone,
        name="Distribuidora Alem",
        contact_name="Pedro",
        business_type="proveedor",
        campaign="supplier",
        merchant_phone=settings.WHATSAPP_ALERT_PHONE
    )
    db.add(sup)
    db.commit()

    handled, reply, action = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, preguntale a Pedro de Distribuidora Alem si el lunes hacen reparto"
    )

    assert handled is True
    assert action == "supplier_inquiry_sent"
    assert "CONSULTA ENVIADA A DISTRIBUIDORA ALEM" in reply
    assert "Pedro" in reply
    assert sup_phone in reply

    # Allow background tasks to execute
    await asyncio.sleep(0.05)

    # Verify Meta template dispatch
    mock_tpl.assert_awaited()
    tpl_call_kwargs = mock_tpl.call_args.kwargs
    assert tpl_call_kwargs["template_name"] == "consulta_proveedor_v1"
    assert tpl_call_kwargs["to_phone"] == sup_phone

    # Verify supplier direct message dispatch
    mock_msg.assert_awaited()
    sent_texts = [call.kwargs.get("text", "") for call in mock_msg.call_args_list]
    assert any("¿El lunes hacen reparto?" in t for t in sent_texts)

    # Verify supplier metadata stored in DB
    db.refresh(sup)
    assert sup.notes is not None
    sup_notes = json.loads(sup.notes)
    assert "last_inquiry" in sup_notes
    assert sup_notes["last_inquiry"]["merchant_phone"] == settings.WHATSAPP_ALERT_PHONE
    assert "¿El lunes hacen reparto?" in sup_notes["last_inquiry"]["inquiry"]


@pytest.mark.asyncio
async def test_merchant_inquiry_unregistered_supplier(db, mock_whatsapp):
    handled, reply, action = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, preguntale a Distribuidora Fantasma si abren mañana"
    )
    assert handled is True
    assert action == "supplier_not_found"
    assert "Distribuidora Fantasma" in reply
    assert "No encontré a" in reply


@pytest.mark.asyncio
async def test_merchant_inquiry_missing_info(db, mock_whatsapp):
    handled, reply, action = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, preguntale a"
    )
    assert handled is True
    assert action == "supplier_inquiry_missing_info"
    assert "¿A qué proveedor querés que le consulte" in reply


def test_supplier_reply_relayed_to_merchant_webhook(db, mock_whatsapp):
    mock_msg, mock_tpl, _ = mock_whatsapp

    # Create supplier who received an inquiry from merchant 5493434111222
    merchant_phone = "5493434111222"
    sup_phone = "5493434666555"
    sup = Prospect(
        phone=sup_phone,
        name="Distribuidora Alem",
        contact_name="Pedro",
        business_type="proveedor",
        campaign="supplier",
        merchant_phone=merchant_phone,
        notes=json.dumps({
            "merchant_phone": merchant_phone,
            "last_inquiry": {
                "merchant_phone": merchant_phone,
                "merchant_biz": "Almacén Don Carlos",
                "merchant_owner": "Carlos",
                "inquiry": "¿El lunes hacen reparto?",
                "timestamp": "2026-09-12T10:00:00"
            }
        })
    )
    db.add(sup)
    db.commit()

    # Supplier replies on WhatsApp
    payload = {
        "phone": sup_phone,
        "message": "Hola Carlos, sí el lunes repartimos por tu zona a partir de las 9:00 hs normal."
    }
    res = client.post("/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["action"] == "supplier_reply_relayed"
    assert data["merchant_phone"] == merchant_phone

    # Verify WhatsApp messages sent
    mock_msg.assert_awaited()
    # Find message sent to merchant
    merchant_call = [c for c in mock_msg.call_args_list if c.kwargs.get("to_phone") == merchant_phone]
    assert len(merchant_call) >= 1
    merchant_text = merchant_call[0].kwargs.get("text", "")
    assert "RESPUESTA DE TU PROVEEDOR" in merchant_text
    assert "Tu consulta fue:" in merchant_text
    assert "¿El lunes hacen reparto?" in merchant_text
    assert "Hola Carlos, sí el lunes repartimos por tu zona a partir de las 9:00 hs normal." in merchant_text

    # Find ack sent to supplier
    sup_call = [c for c in mock_msg.call_args_list if c.kwargs.get("to_phone") == sup_phone]
    assert len(sup_call) >= 1
    sup_text = sup_call[0].kwargs.get("text", "")
    assert "Ya le transmití tu respuesta al comercio" in sup_text


def test_onboarded_client_inquiry_via_webhook(db, mock_whatsapp):
    mock_msg, mock_tpl, _ = mock_whatsapp

    client_phone = "5493434888999"
    sup_phone = "5493434777666"

    # Register client and their supplier
    c_prospect = Prospect(
        phone=client_phone,
        name="Kiosco Avenida",
        contact_name="Mariana",
        campaign="ai_agency",
        status="in_conversation"
    )
    s_prospect = Prospect(
        phone=sup_phone,
        name="Distribuidora Central",
        contact_name="Esteban",
        business_type="proveedor",
        campaign="supplier",
        merchant_phone=client_phone
    )
    db.add_all([c_prospect, s_prospect])
    db.commit()

    payload = {
        "phone": client_phone,
        "message": "Sofi, consultale a Esteban de Distribuidora Central si tienen stock de galletitas Oreo"
    }
    res = client.post("/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["action"] == "supplier_inquiry_sent"
    assert "CONSULTA ENVIADA A DISTRIBUIDORA CENTRAL" in data["reply"]

    # Verify supplier received inquiry
    mock_tpl.assert_awaited()
    tpl_call = mock_tpl.call_args.kwargs
    assert tpl_call["to_phone"] == sup_phone
    assert tpl_call["template_name"] == "consulta_proveedor_v1"


def test_client_manual_and_faq_inquiry_documentation():
    manual = get_client_manual_text()
    assert "Consultas directas a proveedores" in manual
    assert "preguntale a" in manual.lower()

    faq = get_client_faq_text()
    assert "consultas o preguntas a un proveedor" in faq.lower()
    assert "secretaria ejecutiva de compras" in faq.lower()
