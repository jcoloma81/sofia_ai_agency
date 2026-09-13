import pytest
import json
import asyncio
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from main import app
from app.config.settings import settings
from app.database import Base, get_db
from app.models.prospect import Prospect, SupplierDraftOrder, MerchantProduct, WebhookEvent
from tests.conftest import test_engine, TestingSessionLocal

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


def assert_semantic_quality(text: str, context_label: str = ""):
    """
    Semantic Quality Gate:
    Ensures that Sofia NEVER outputs awkward, broken or technical phrases to any user.
    """
    assert text is not None, f"Response is None in {context_label}"
    assert "None" not in text, f"Found literal 'None' in {context_label}: {text}"
    assert "(Director)" not in text, f"Leaked internal role '(Director)' in {context_label}: {text}"
    assert "Javier de Javier" not in text, f"Redundant self-referencing phrasing in {context_label}: {text}"
    assert "el titular de tu comercio" not in text, f"Unresolved placeholder in {context_label}: {text}"
    assert "500 Internal" not in text, f"Leaked internal error in {context_label}: {text}"


@pytest.mark.asyncio
async def test_e2e_merchant_full_pipeline_and_semantic_quality(db, mock_whatsapp):
    mock_msg, mock_tpl, _ = mock_whatsapp
    merchant_phone = "5493434112233"
    supplier_phone = "5493434778899"

    # 1. Onboard a real merchant
    merchant = Prospect(
        name="Ferretería Avenida",
        contact_name="Carlos",
        phone=merchant_phone,
        business_type="ferreteria",
        campaign="client_onboarding",
        status="in_conversation"
    )
    db.add(merchant)
    db.commit()

    # STEP A: Merchant greets Sofia via WhatsApp Webhook
    resp_greeting = client.post("/webhook", json={
        "phone": merchant_phone,
        "message": "hola"
    })
    assert resp_greeting.status_code == 200
    data_g = resp_greeting.json()
    reply_g = data_g.get("reply", "")
    assert_semantic_quality(reply_g, "greeting")
    assert "Carlos" in reply_g
    assert "Ferretería Avenida" in reply_g

    # STEP B: Merchant asks for suppliers (currently empty) via Webhook
    resp_sups_empty = client.post("/webhook", json={
        "phone": merchant_phone,
        "message": "proveedores"
    })
    assert resp_sups_empty.status_code == 200
    data_se = resp_sups_empty.json()
    reply_se = data_se.get("reply", "")
    assert_semantic_quality(reply_se, "empty_suppliers")
    assert "No tenés proveedores" in reply_se or "PROVEEDORES" in reply_se
    # Crucial gate: must NOT pitch a sales meeting to an existing onboarded merchant!
    assert "reunión" not in reply_se.lower()

    # STEP C: Merchant registers a supplier via Webhook
    resp_reg = client.post("/webhook", json={
        "phone": merchant_phone,
        "message": f"Sofi, agendá al proveedor Pinturas del Litoral al {supplier_phone}"
    })
    assert resp_reg.status_code == 200
    data_reg = resp_reg.json()
    reply_reg = data_reg.get("reply", "")
    assert_semantic_quality(reply_reg, "supplier_registration")
    assert "PROVEEDOR REGISTRADO" in reply_reg
    assert "Pinturas del Litoral" in reply_reg
    assert "Carlos de Ferretería Avenida" in reply_reg
    assert "Sofía - Ferretería Avenida" in reply_reg

    # STEP D: Merchant asks Sofia to inquire the supplier
    resp_inq = client.post("/webhook", json={
        "phone": merchant_phone,
        "message": "Sofi, preguntale a Pinturas del Litoral si tienen latex blanco de 20 litros"
    })
    assert resp_inq.status_code == 200
    data_inq = resp_inq.json()
    reply_inq = data_inq.get("reply", "")
    assert_semantic_quality(reply_inq, "direct_inquiry")
    assert "CONSULTA ENVIADA" in reply_inq
    assert "Pinturas del Litoral" in reply_inq
    assert ("latex" in reply_inq.lower() or "látex" in reply_inq.lower()) and "20 litros" in reply_inq.lower()

    # Check that supplier was addressed with clean identity
    await asyncio.sleep(0.05)
    sent_texts_to_sup = [call.kwargs.get("text", "") for call in mock_msg.call_args_list if call.kwargs.get("to_phone") == supplier_phone]
    assert any("Carlos de Ferretería Avenida" in t for t in sent_texts_to_sup)

    # STEP E: Supplier replies to Sofia via Webhook -> Relayed to Carlos
    resp_reply = client.post("/webhook", json={
        "phone": supplier_phone,
        "message": "Hola Carlos, sí tenemos 15 tachos en stock"
    })
    assert resp_reply.status_code == 200
    assert resp_reply.json().get("status") == "success"
    assert resp_reply.json().get("action") == "supplier_reply_relayed"

    # Verify relay alert sent to Carlos
    sent_texts_to_carlos = [call.kwargs.get("text", "") for call in mock_msg.call_args_list if call.kwargs.get("to_phone") == merchant_phone]
    assert any("RESPUESTA DE TU PROVEEDOR" in t for t in sent_texts_to_carlos)
    assert any("15 tachos en stock" in t for t in sent_texts_to_carlos)

    # STEP F: Merchant asks for basket state via Webhook
    resp_basket = client.post("/webhook", json={
        "phone": merchant_phone,
        "message": "¿Qué tengo para pedirle a Pinturas del Litoral?"
    })
    assert resp_basket.status_code == 200
    reply_b = resp_basket.json().get("reply", "")
    assert_semantic_quality(reply_b, "basket_query")
    assert "no tenés" in reply_b.lower() or "canasta" in reply_b.lower() or "pedido" in reply_b.lower()
    assert "reunión" not in reply_b.lower()


@pytest.mark.asyncio
async def test_e2e_boss_director_semantic_quality(db, mock_whatsapp):
    mock_msg, mock_tpl, _ = mock_whatsapp
    boss_phone = settings.WHATSAPP_ALERT_PHONE
    sup_phone = "5493434661122"

    # 1. Reset boss record
    boss = db.query(Prospect).filter(Prospect.phone == boss_phone).first()
    if not boss:
        boss = Prospect(
            phone=boss_phone,
            name="Javier Coloma (Director)",
            contact_name="Javier",
            campaign="boss_mode",
            status="director"
        )
        db.add(boss)
    else:
        boss.name = "Javier Coloma (Director)"
        boss.campaign = "boss_mode"
        boss.status = "director"
    db.commit()

    # Boss registers a supplier via Webhook
    resp_boss = client.post("/webhook", json={
        "phone": boss_phone,
        "message": f"Sofi, agendá al proveedor Mayorista Central al {sup_phone}"
    })
    assert resp_boss.status_code == 200
    data_b = resp_boss.json()
    reply_b = data_b.get("reply", "")
    assert_semantic_quality(reply_b, "boss_supplier_registration")
    assert "PROVEEDOR REGISTRADO" in reply_b
    assert "Javier Coloma" in reply_b

    # Boss asks for suppliers via Webhook
    resp_sups = client.post("/webhook", json={
        "phone": boss_phone,
        "message": "proveedores"
    })
    assert resp_sups.status_code == 200
    reply_sups = resp_sups.json().get("reply", "")
    assert_semantic_quality(reply_sups, "boss_suppliers_list")
    assert "Mayorista Central" in reply_sups


def test_health_check_endpoint_and_database_verification():
    from app.database import verify_database_health

    # 1. Unit check of db health
    assert verify_database_health(test_engine) is True

    # 2. HTTP check of /health
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "healthy"
    assert data.get("database") == "connected"
    assert data.get("platform") == "sofia_ai_agency"
