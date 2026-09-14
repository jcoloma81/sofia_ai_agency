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
    parse_supplier_inquiry_intent,
    parse_supplier_registration_intent,
    parse_supplier_deletion_intent,
    parse_supplier_phone_update_intent
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
    assert "lunes" in r1.get("inquiry_text", "").lower()
    assert "reparto" in r1.get("inquiry_text", "").lower()

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

    # 6. Preventista inquiry
    r6 = await parse_supplier_inquiry_intent("Sofi, preguntale al preventista Carlos si tienen stock de alfajores")
    assert r6.get("is_supplier_inquiry") is True
    assert "Carlos" in r6.get("supplier_name", "")
    assert "stock" in r6.get("inquiry_text", "").lower()

    # 7. Corredor inquiry
    r7 = await parse_supplier_inquiry_intent("Sofi, consultale al corredor Martín si el lunes hay reparto")
    assert r7.get("is_supplier_inquiry") is True
    assert "Martín" in r7.get("supplier_name", "") or "Martin" in r7.get("supplier_name", "")


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
    assert tpl_call_kwargs["template_name"] == "consulta_logistica_proveedor_v1"
    assert tpl_call_kwargs["to_phone"] == sup_phone

    # Verify supplier direct message dispatch
    mock_msg.assert_awaited()
    sent_texts = [call.kwargs.get("text", "") for call in mock_msg.call_args_list]
    assert any("reparto" in t.lower() and "lunes" in t.lower() for t in sent_texts)

    # Verify supplier metadata stored in DB
    db.refresh(sup)
    assert sup.notes is not None
    sup_notes = json.loads(sup.notes)
    assert "last_inquiry" in sup_notes
    assert sup_notes["last_inquiry"]["merchant_phone"] == settings.WHATSAPP_ALERT_PHONE
    assert "reparto" in sup_notes["last_inquiry"]["inquiry"].lower() and "lunes" in sup_notes["last_inquiry"]["inquiry"].lower()


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
    assert tpl_call["template_name"] == "consulta_logistica_proveedor_v1"


def test_client_manual_and_faq_inquiry_documentation():
    manual = get_client_manual_text()
    assert "Consultas directas a proveedores" in manual
    assert "preguntale a" in manual.lower()

    faq = get_client_faq_text()
    assert "consultas o preguntas a un proveedor" in faq.lower()
    assert "secretaria ejecutiva de compras" in faq.lower()


def test_supplier_reply_layer1_quoted_swipe(db, mock_whatsapp):
    mock_msg, mock_tpl, _ = mock_whatsapp

    sup_phone = "5493434555444"
    m1_phone = "5493434111222"
    m2_phone = "5493434999888"

    # Carlos supplies both Merchant 1 (Alem) and Merchant 2 (San Martín)
    sup_m1 = Prospect(
        phone=sup_phone,
        name="Distribuidora Carlos",
        contact_name="Carlos",
        business_type="proveedor",
        campaign="supplier",
        merchant_phone=m1_phone,
        notes=json.dumps({
            "merchant_phone": m1_phone,
            "last_inquiry": {
                "merchant_phone": m1_phone,
                "merchant_biz": "Ferretería Alem",
                "merchant_owner": "Javier",
                "inquiry": "¿Tenés stock de martillos?",
                "timestamp": "2026-09-14T10:00:00",
                "replied": False
            }
        })
    )
    sup_m2 = Prospect(
        phone=sup_phone,
        name="Distribuidora Carlos",
        contact_name="Carlos",
        business_type="proveedor",
        campaign="supplier",
        merchant_phone=m2_phone,
        notes=json.dumps({
            "merchant_phone": m2_phone,
            "last_inquiry": {
                "merchant_phone": m2_phone,
                "merchant_biz": "Corralón San Martín",
                "merchant_owner": "Martín",
                "inquiry": "¿A qué hora pasa el reparto hoy?",
                "timestamp": "2026-09-14T10:05:00",
                "replied": False
            }
        })
    )
    db.add_all([sup_m1, sup_m2])
    db.commit()

    # Carlos replies quoting Alem's inquiry
    payload = {
        "phone": sup_phone,
        "message": "Sí, me quedan 10 cajas a $5.000",
        "quoted": "¿Tenés stock de martillos?"
    }
    res = client.post("/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["action"] == "supplier_reply_relayed"
    assert data["merchant_phone"] == m1_phone

    # Verify Alem's inquiry is marked replied, but San Martín is STILL unreplied
    db.refresh(sup_m1)
    db.refresh(sup_m2)
    m1_notes = json.loads(sup_m1.notes)
    m2_notes = json.loads(sup_m2.notes)
    assert m1_notes["last_inquiry"]["replied"] is True
    assert m2_notes["last_inquiry"]["replied"] is False


def test_supplier_reply_layer2_mention_merchant_name(db, mock_whatsapp):
    mock_msg, mock_tpl, _ = mock_whatsapp

    sup_phone = "5493434555333"
    m1_phone = "5493434111333"
    m2_phone = "5493434999777"

    sup_m1 = Prospect(
        phone=sup_phone,
        name="Distribuidora Carlos",
        contact_name="Carlos",
        business_type="proveedor",
        campaign="supplier",
        merchant_phone=m1_phone,
        notes=json.dumps({
            "merchant_phone": m1_phone,
            "last_inquiry": {
                "merchant_phone": m1_phone,
                "merchant_biz": "Ferretería Alem",
                "merchant_owner": "Javier",
                "inquiry": "¿Tenés stock de martillos?",
                "timestamp": "2026-09-14T10:00:00",
                "replied": False
            }
        })
    )
    sup_m2 = Prospect(
        phone=sup_phone,
        name="Distribuidora Carlos",
        contact_name="Carlos",
        business_type="proveedor",
        campaign="supplier",
        merchant_phone=m2_phone,
        notes=json.dumps({
            "merchant_phone": m2_phone,
            "last_inquiry": {
                "merchant_phone": m2_phone,
                "merchant_biz": "Corralón San Martín",
                "merchant_owner": "Martín",
                "inquiry": "¿A qué hora pasa el camión?",
                "timestamp": "2026-09-14T10:05:00",
                "replied": False
            }
        })
    )
    db.add_all([sup_m1, sup_m2])
    db.commit()

    # Carlos writes without quote, but mentions Alem explicitly
    payload = {
        "phone": sup_phone,
        "message": "Para los de Alem: sí, me quedan 10 cajas disponibles."
    }
    res = client.post("/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["action"] == "supplier_reply_relayed"
    assert data["merchant_phone"] == m1_phone

    db.refresh(sup_m1)
    db.refresh(sup_m2)
    assert json.loads(sup_m1.notes)["last_inquiry"]["replied"] is True
    assert json.loads(sup_m2.notes)["last_inquiry"]["replied"] is False


def test_supplier_reply_layer3_collision_disambiguation_flow(db, mock_whatsapp):
    mock_msg, mock_tpl, _ = mock_whatsapp

    sup_phone = "5493434555222"
    m1_phone = "5493434111444"
    m2_phone = "5493434999666"

    sup_m1 = Prospect(
        phone=sup_phone,
        name="Distribuidora Carlos",
        contact_name="Carlos",
        business_type="proveedor",
        campaign="supplier",
        merchant_phone=m1_phone,
        notes=json.dumps({
            "merchant_phone": m1_phone,
            "last_inquiry": {
                "merchant_phone": m1_phone,
                "merchant_biz": "Ferretería Alem",
                "merchant_owner": "Javier",
                "inquiry": "¿Tenés stock de martillos?",
                "timestamp": "2026-09-14T10:00:00",
                "replied": False
            }
        })
    )
    sup_m2 = Prospect(
        phone=sup_phone,
        name="Distribuidora Carlos",
        contact_name="Carlos",
        business_type="proveedor",
        campaign="supplier",
        merchant_phone=m2_phone,
        notes=json.dumps({
            "merchant_phone": m2_phone,
            "last_inquiry": {
                "merchant_phone": m2_phone,
                "merchant_biz": "Corralón San Martín",
                "merchant_owner": "Martín",
                "inquiry": "¿A qué hora pasa el camión?",
                "timestamp": "2026-09-14T10:05:00",
                "replied": False
            }
        })
    )
    db.add_all([sup_m1, sup_m2])
    db.commit()

    # Step 1: Carlos writes ambiguous message ("Sí, tenemos stock") without quote or name
    payload1 = {
        "phone": sup_phone,
        "message": "Sí, tenemos stock de sobra"
    }
    res1 = client.post("/webhook", json=payload1)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "success"
    assert data1["action"] == "supplier_disambiguation_requested"
    assert "Ferretería Alem" in data1["reply"]
    assert "Corralón San Martín" in data1["reply"]

    # Inquiries are still unreplied
    db.refresh(sup_m1)
    db.refresh(sup_m2)
    assert json.loads(sup_m1.notes)["last_inquiry"]["replied"] is False
    assert json.loads(sup_m2.notes)["last_inquiry"]["replied"] is False

    # Step 2: Carlos replies "1"
    payload2 = {
        "phone": sup_phone,
        "message": "1"
    }
    res2 = client.post("/webhook", json=payload2)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "success"
    assert data2["action"] == "supplier_reply_relayed"
    assert data2["merchant_phone"] == m1_phone
    assert data2.get("disambiguated") is True

    # Now Alem is replied, and San Martín is still waiting
    db.refresh(sup_m1)
    db.refresh(sup_m2)
    assert json.loads(sup_m1.notes)["last_inquiry"]["replied"] is True
    assert json.loads(sup_m2.notes)["last_inquiry"]["replied"] is False
    assert "pending_disambiguation" not in json.loads(sup_m1.notes)


@pytest.mark.asyncio
async def test_preventista_and_corredor_synonyms():
    # 1. Registration with "preventista"
    r_prev = await parse_supplier_registration_intent("Sofi, agendá al preventista Carlos de Arcor al 3434556677")
    assert r_prev.get("is_supplier_registration") is True
    assert "Carlos" in (r_prev.get("contact_name") or "") or "Carlos" in (r_prev.get("supplier_name") or "")
    assert "3434556677" in (r_prev.get("phone") or "")

    # 2. Registration with "corredor"
    r_corr = await parse_supplier_registration_intent("Sofi, anotá al corredor Martín de Molinos al 3434112233")
    assert r_corr.get("is_supplier_registration") is True
    assert "3434112233" in (r_corr.get("phone") or "")

    # 3. Deletion with "preventista"
    r_del = parse_supplier_deletion_intent("Sofi, dar de baja al preventista Carlos")
    assert r_del.get("is_supplier_deletion") is True
    assert "Carlos" in (r_del.get("supplier_name") or "")

    # 4. Phone change with "preventista"
    r_chg = await parse_supplier_phone_update_intent("Sofi, el preventista Carlos de Arcor cambió de número al 3434998877")
    assert r_chg.get("is_supplier_phone_update") is True
    assert "3434998877" in (r_chg.get("new_phone") or "")

