import pytest
import json
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from main import app
from app.database import Base, get_db
from app.models.prospect import Prospect
from tests.conftest import test_engine, TestingSessionLocal
from app.services import brain, whatsapp, alerts

# Ensure all tables are created on the test DB
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
         patch("app.services.whatsapp.notify_javier_meeting_scheduled", new_callable=AsyncMock) as mock_alert:
        mock_send.return_value = True
        yield mock_send, mock_alert

def test_health_check():
    """Verify health and root endpoints."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["platform"] == "sofia_ai_agency"

    root_res = client.get("/")
    assert root_res.status_code == 200
    assert "Sofía" in root_res.text

def test_webhook_incoming_inquiry(db, mock_whatsapp):
    mock_send, mock_alert = mock_whatsapp

    payload = {
        "phone": "5493447400964",
        "message": "Hola, ¿cómo funciona el agente de inteligencia artificial para ventas?",
        "complex_name": "Distribuidora El Remanso",
        "contact_name": "Carlos",
        "city": "Colón"
    }

    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["meeting_confirmed"] is False
    assert "asesor" in data["reply"].lower() or "charla" in data["reply"].lower() or "demo" in data["reply"].lower()

    # Verify prospect in DB
    prospect = db.query(Prospect).filter(Prospect.phone == "5493447400964").first()
    assert prospect is not None
    assert prospect.name == "Distribuidora El Remanso"
    assert prospect.contact_name == "Carlos"
    assert prospect.city == "Colón"
    assert prospect.status in ["in_conversation", "demo_requested"]

    # History contains both messages
    history = json.loads(prospect.conversation_history)
    assert len(history) == 2
    assert history[0]["sender"] == "prospect"
    assert history[1]["sender"] == "ai"

    # WhatsApp response was dispatched
    mock_send.assert_awaited()
    mock_alert.assert_not_awaited()

def test_webhook_meeting_scheduled_triggers_alert(db, mock_whatsapp):
    mock_send, mock_alert = mock_whatsapp

    prospect = Prospect(
        phone="5493456548809",
        name="Mayorista San Martín",
        contact_name="Martín",
        city="Federación",
        status="in_conversation",
        conversation_history="[]",
        campaign="ai_agency"
    )
    db.add(prospect)
    db.commit()

    # Prospect agrees to meeting
    payload = {
        "phone": "5493456548809",
        "message": "Dale perfecto, llamame mañana a las 16 hs al celular y lo vemos"
    }

    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["meeting_confirmed"] is True

    # Verify prospect updated in DB
    db.refresh(prospect)
    assert prospect.status == "meeting_scheduled"
    assert "mañana a las 16" in prospect.meeting_details.lower()
    assert prospect.meeting_scheduled_at is not None

    # Verify alert dispatched to Javier
    mock_alert.assert_awaited_once()
    call_kwargs = mock_alert.call_args.kwargs
    assert call_kwargs["prospect_name"] == "Mayorista San Martín"
    assert call_kwargs["contact_name"] == "Martín"
    assert call_kwargs["phone"] == "5493456548809"
    assert call_kwargs["campaign"] == "ai_agency"

def test_start_outreach_endpoint(db, mock_whatsapp):
    mock_send, mock_alert = mock_whatsapp

    payload = {
        "phone": "5493435133108",
        "name": "Corralón del Litoral",
        "contact_name": "Roberto",
        "city": "Paraná",
        "campaign": "ai_agency",
        "business_type": "corralon"
    }

    response = client.post("/api/v1/outreach/start-outreach", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "outreach_started"

    # Verify in DB
    prospect = db.query(Prospect).filter(Prospect.phone == "5493435133108").first()
    assert prospect is not None
    assert prospect.status == "contacted"
    assert prospect.business_type == "corralon"
    assert prospect.campaign == "ai_agency"

    # Opening pitch sent
    mock_send.assert_awaited()

def test_ai_agency_outreach_pitch_content(db, mock_whatsapp):
    mock_send, _ = mock_whatsapp

    payload = {
        "phone": "5493434991122",
        "name": "Distribuidora Río Paraná",
        "contact_name": "Martín",
        "city": "Paraná",
        "campaign": "ai_agency",
        "business_type": "distribuidora"
    }

    res = client.post("/api/v1/outreach/start-outreach", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "outreach_started"
    assert data["campaign"] == "ai_agency"

    # Verify pitch content
    sent_text = mock_send.call_args[1]["text"]
    assert "100% autónoma" in sent_text
    assert "No soy un bot común de respuestas automáticas" in sent_text
    assert "Google Maps" in sent_text
    assert "entre 12 y 15 empresas de tu interés por día" in sent_text
    assert "alerta" in sent_text.lower()
    assert "Lucas" in sent_text
    assert "Sofía" in sent_text

    lead = db.query(Prospect).filter(Prospect.phone == "5493434991122").first()
    assert lead is not None
    assert lead.campaign == "ai_agency"
    assert lead.business_type == "distribuidora"

def test_sdr_status_and_listing(db):
    response = client.get("/api/v1/outreach/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert "+54 9 343 572-0312" in data["agent_phone"]
    assert "+54 9 343 453-6447" in data["alert_phone"]

    list_res = client.get("/api/v1/outreach/prospects")
    assert list_res.status_code == 200
    assert isinstance(list_res.json(), list)

def test_meta_webhook_verification():
    """Verify Meta handshake GET /webhook."""
    # 1. Successful handshake
    res = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "1158201444",
            "hub.verify_token": "sofia_meta_secret_token_2026"
        }
    )
    assert res.status_code == 200
    assert res.text == "1158201444"

    # Also test at /api/v1/webhook
    res_v1 = client.get(
        "/api/v1/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "998877",
            "hub.verify_token": "sofia_meta_secret_token_2026"
        }
    )
    assert res_v1.status_code == 200
    assert res_v1.text == "998877"

    # 2. Token mismatch
    res_fail = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "1158201444",
            "hub.verify_token": "wrong_token"
        }
    )
    assert res_fail.status_code == 403

def test_meta_webhook_incoming_message(db, mock_whatsapp):
    mock_send, mock_alert = mock_whatsapp

    meta_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "2238368880345692",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551969785",
                                "phone_number_id": "1221681157704738"
                            },
                            "contacts": [
                                {
                                    "profile": {
                                        "name": "Carlos Gomez"
                                    },
                                    "wa_id": "5491166778899"
                                }
                            ],
                            "messages": [
                                {
                                    "from": "5491166778899",
                                    "id": "wamid.HBgLNTQ5MzQzNDUzNjQ0NxUCABEYEjA...",
                                    "timestamp": "1725740000",
                                    "text": {
                                        "body": "Hola Sofía, contame cómo funciona el servicio"
                                    },
                                    "type": "text"
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    res = client.post("/webhook", json=meta_payload)
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # Verify prospect in DB
    prospect = db.query(Prospect).filter(Prospect.phone == "5491166778899").first()
    assert prospect is not None
    assert prospect.contact_name == "Carlos Gomez"
    mock_send.assert_awaited()

def test_meta_webhook_status_update(db, mock_whatsapp):
    mock_send, _ = mock_whatsapp

    meta_status_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "2238368880345692",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551969785",
                                "phone_number_id": "1221681157704738"
                            },
                            "statuses": [
                                {
                                    "id": "wamid.HBgL...",
                                    "status": "delivered",
                                    "timestamp": "1725740000",
                                    "recipient_id": "5493434536447"
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    res = client.post("/webhook", json=meta_status_payload)
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    mock_send.assert_not_awaited()

def test_whapi_webhook_format_and_self_filter(db, mock_whatsapp):
    mock_send, mock_alert = mock_whatsapp

    # 1. Test message from self is ignored
    self_payload = {
        "messages": [
            {
                "id": "msg_self_1",
                "chat_id": "5493447400964@s.whatsapp.net",
                "from_me": True,
                "text": {"body": "Mensaje enviado por la IA"}
            }
        ]
    }
    res_self = client.post("/webhook", json=self_payload)
    assert res_self.status_code == 200
    assert res_self.json()["status"] == "ignored"

    # 2. Test valid incoming Whapi message from prospect
    whapi_payload = {
        "messages": [
            {
                "id": "msg_whapi_123",
                "chat_id": "5493447400964@s.whatsapp.net",
                "from": "5493447400964",
                "from_name": "Juan Carlos",
                "from_me": False,
                "type": "text",
                "text": {"body": "Buenas tardes, ¿cómo funciona el servicio y qué costo tiene?"}
            }
        ]
    }
    res = client.post("/webhook", json=whapi_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    mock_send.assert_awaited()

def test_human_takeover_silences_sofia_for_single_chat(db, mock_whatsapp):
    mock_send, mock_alert = mock_whatsapp

    prospect_a = Prospect(
        phone="5493447400964",
        name="Distribuidora Remanso",
        status="in_conversation",
        conversation_history="[]"
    )
    prospect_b = Prospect(
        phone="5493456548809",
        name="Mayorista Concordia",
        status="in_conversation",
        conversation_history="[]"
    )
    db.add_all([prospect_a, prospect_b])
    db.commit()

    # 1. Javier intervenes manually from mobile
    javier_manual_payload = {
        "messages": [
            {
                "id": "msg_javier_manual_1",
                "chat_id": "5493447400964@s.whatsapp.net",
                "from_me": True,
                "source": "mobile",
                "text": {"body": "Hola Carlos, te escribo yo directamente, Javier"}
            }
        ]
    }
    res_javier = client.post("/webhook", json=javier_manual_payload)
    assert res_javier.status_code == 200
    assert res_javier.json()["status"] == "success"

    # Verify prospect A is in human_takeover
    db.refresh(prospect_a)
    assert prospect_a.status == "human_takeover"

    # 2. Prospect A replies: Sofia MUST remain silent!
    mock_send.reset_mock()
    prospect_a_msg = {
        "messages": [
            {
                "id": "msg_a_reply_1",
                "chat_id": "5493447400964@s.whatsapp.net",
                "from": "5493447400964",
                "from_me": False,
                "text": {"body": "Hola Javier, dale perfecto, hablemos nosotros"}
            }
        ]
    }
    res_a = client.post("/webhook", json=prospect_a_msg)
    assert res_a.status_code == 200
    assert res_a.json()["status"] == "ignored"
    mock_send.assert_not_awaited()

    # 3. Prospect B writes: Sofia DOES respond normally
    prospect_b_msg = {
        "messages": [
            {
                "id": "msg_b_inquiry_1",
                "chat_id": "5493456548809@s.whatsapp.net",
                "from": "5493456548809",
                "from_me": False,
                "text": {"body": "Hola Sofia, ¿cuanto sale el sistema?"}
            }
        ]
    }
    res_b = client.post("/webhook", json=prospect_b_msg)
    assert res_b.status_code == 200
    assert res_b.json()["status"] == "success"
    mock_send.assert_awaited()

    # 4. Javier reactivates Prospect A from his private alert phone
    reactivate_payload = {
        "messages": [
            {
                "id": "msg_reactivate_1",
                "chat_id": "5493434536447@s.whatsapp.net",
                "from": "5493434536447",
                "from_me": False,
                "text": {"body": "activar 400964"}
            }
        ]
    }
    res_reactivate = client.post("/webhook", json=reactivate_payload)
    assert res_reactivate.status_code == 200
    assert res_reactivate.json()["status"] == "success"
    assert res_reactivate.json()["action"] == "lead_reactivated"

    db.refresh(prospect_a)
    assert prospect_a.status == "in_conversation"

def test_whapi_voice_note_processing(db, mock_whatsapp):
    mock_send, mock_alert = mock_whatsapp

    voice_msg_payload = {
        "messages": [
            {
                "id": "msg_voice_test_1",
                "chat_id": "5493435133108@s.whatsapp.net",
                "from": "5493435133108",
                "from_me": False,
                "type": "voice",
                "from_name": "Esteban",
                "voice": {
                    "id": "audio_123",
                    "mime_type": "audio/ogg; codecs=opus",
                    "link": "https://s3.example.com/audio.oga",
                    "seconds": 8
                }
            }
        ]
    }

    dummy_audio_bytes = b"OGG_OPUS_SAMPLE_DATA"
    with patch("httpx.AsyncClient.get") as mock_get, \
         patch("app.services.brain.generate_ai_response", new_callable=AsyncMock) as mock_ai:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.content = dummy_audio_bytes
        mock_get.return_value = mock_resp
        mock_ai.return_value = ("Hola Esteban, te cuento que para ver los costos y la demo podemos coordinar una charla de 10 minutos.", False, None)

        res = client.post("/webhook", json=voice_msg_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"

        # Verify prospect recorded
        prospect = db.query(Prospect).filter(Prospect.phone == "5493435133108").first()
        assert prospect is not None
        assert prospect.contact_name == "Esteban"
        history = json.loads(prospect.conversation_history)
        assert any("Nota de voz" in h.get("text", "") for h in history)
        mock_send.assert_awaited()

def test_batch_outreach(db, mock_whatsapp):
    mock_send, _ = mock_whatsapp

    batch_payload = {
        "leads": [
            {
                "phone": "5493434775566",
                "name": "Ferretería y Bulonera Central",
                "contact_name": "Valeria",
                "city": "Paraná",
                "campaign": "ai_agency",
                "business_type": "bulonera"
            }
        ]
    }

    res = client.post("/api/v1/outreach/start-batch-outreach", json=batch_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "batch_completed"
    assert data["total"] == 1
    assert data["results"][0]["status"] == "outreach_started"
    assert data["results"][0]["campaign"] == "ai_agency"

def test_rule_based_fallback_engine():
    # Test rejection
    resp, is_meeting, details = brain.rule_based_consultative_response(
        "No me interesa, gracias", contact_name="Juan"
    )
    assert "Entendido totalmente" in resp
    assert is_meeting is False

    # Test presence / greeting
    resp, is_meeting, details = brain.rule_based_consultative_response(
        "Hola Sofía, ¿estás?", contact_name="María"
    )
    assert "acá estoy" in resp
    assert is_meeting is False

    # Test inquiry
    resp, is_meeting, details = brain.rule_based_consultative_response(
        "¿Cuánto cuesta el servicio?", contact_name="Carlos", campaign="ai_agency"
    )
    assert "demo en vivo" in resp
    assert is_meeting is False

    # Test meeting booking
    resp, is_meeting, details = brain.rule_based_consultative_response(
        "Dale, coordinemos para el martes a las 10 hs", contact_name="Carlos"
    )
    assert is_meeting is True
    assert "martes a las 10" in details.lower()
    assert "¡Perfecto Carlos!" in resp

@pytest.mark.asyncio
async def test_dual_alert_dispatch():
    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_wa, \
         patch("app.services.whatsapp.send_email_alert", new_callable=AsyncMock) as mock_email:
        mock_wa.return_value = True
        mock_email.return_value = True

        await whatsapp.notify_javier_meeting_scheduled(
            prospect_name="Distribuidora Paraná",
            contact_name="Pedro",
            phone="5493434123456",
            city="Paraná",
            meeting_details="Jueves 15:00 hs",
            last_message="Dale, llamame el jueves a las 15 hs",
            campaign="ai_agency"
        )

        mock_wa.assert_awaited_once()
        mock_email.assert_awaited_once()
        assert "5493434536447" in mock_wa.call_args[1]["to_phone"]
        assert "Distribuidora Paraná" in mock_email.call_args[1]["subject"]

def test_demo_request_via_meta_webhook(db, mock_whatsapp):
    """Verify that when someone texts DEMO, Sofia sends the friendly reply and marks demo_requested."""
    meta_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "2238368880345692",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "5493435720312", "phone_number_id": "1306573512540922"},
                            "contacts": [{"profile": {"name": "Martín Distribuciones"}, "wa_id": "5493439998877"}],
                            "messages": [
                                {
                                    "from": "5493439998877",
                                    "id": "wamid.DEMO_TEST_MSG_01",
                                    "timestamp": "1725540000",
                                    "type": "text",
                                    "text": {"body": "DEMO"}
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    response = client.post("/webhook", json=meta_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["demo_requested"] is True
    assert "video demo" in data["reply"]
    assert "gracias por escribirme" in data["reply"].lower()

    # Verify prospect status in db
    prospect = db.query(Prospect).filter(Prospect.phone == "5493439998877").first()
    assert prospect is not None
    assert prospect.status == "demo_requested"
