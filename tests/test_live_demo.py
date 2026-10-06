import pytest
from unittest.mock import patch, AsyncMock
from app.services.live_demo import live_demo_service
from app.services import brain
from app.services.boss_mode import process_boss_message

@pytest.mark.asyncio
async def test_live_demo_service_lifecycle():
    # Test initial state
    live_demo_service.reset_demo_mode()
    assert live_demo_service.get_active_demo() is None

    # Test activation
    ok, msg = live_demo_service.set_demo_mode("consultorio", duration_minutes=30)
    assert ok is True
    assert "Consultorio Médico" in msg
    assert live_demo_service.get_active_demo() == "consultorio"

    # Test prompt retrieval
    prompt = live_demo_service.get_demo_prompt("consultorio")
    assert "San Lucas" in prompt
    assert "$18.000" in prompt

    # Test reset
    reset_msg = live_demo_service.reset_demo_mode()
    assert "finalizado" in reset_msg
    assert live_demo_service.get_active_demo() is None

@pytest.mark.asyncio
async def test_live_demo_boss_commands():
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        # Test #demo help/menu
        handled, reply, action = await process_boss_message(db, "5493435111111", "#demo")
        assert handled is True
        assert "Comandos de Demostración" in reply
        assert action == "demo_help"

        # Test #demo veterinaria
        handled, reply, action = await process_boss_message(db, "5493435111111", "#demo veterinaria")
        assert handled is True
        assert "MODO DEMO ACTIVADO" in reply
        assert "Veterinaria" in reply
        assert action == "demo_activated"
        assert live_demo_service.get_active_demo() == "veterinaria"

        # Test #demo status
        handled, reply, action = await process_boss_message(db, "5493435111111", "#demo status")
        assert handled is True
        assert "VETERINARIA" in reply
        assert action == "demo_status"

        # Test #demo reset
        handled, reply, action = await process_boss_message(db, "5493435111111", "#demo reset")
        assert handled is True
        assert "finalizado" in reply
        assert action == "demo_reset"
        assert live_demo_service.get_active_demo() is None
    finally:
        db.close()

@pytest.mark.asyncio
async def test_generate_ai_response_uses_live_demo():
    live_demo_service.set_demo_mode("veterinaria", duration_minutes=15)
    try:
        # Mock httpx in brain so we don't call real Gemini in unit test
        mock_response = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "¡Hola! Para vacunar a tu perro tenemos turno hoy a las 17 hs."}]
                }
            }]
        }
        from unittest.mock import MagicMock
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = mock_response

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_res

            reply, is_meeting, details = await brain.generate_ai_response(
                incoming_text="Hola, tienen vacunas para mi perro?",
                conversation_history=[],
                campaign="ai_agency"
            )
            assert "vacunar" in reply
            # Verify system instruction contains the veterinary prompt
            call_args = mock_post.call_args[1]
            payload = call_args["json"]
            system_instruction = payload["systemInstruction"]["parts"][0]["text"]
            assert "Veterinaria & Pet Shop Huellitas" in system_instruction
    finally:
        live_demo_service.reset_demo_mode()


@pytest.mark.asyncio
async def test_live_demo_webhook_mirror_alert():
    from fastapi.testclient import TestClient
    from main import app
    from unittest.mock import patch, AsyncMock
    client = TestClient(app)
    live_demo_service.set_demo_mode("consultorio", duration_minutes=30)
    try:
        payload = {
            "messages": [{
                "from": "5493439998877", # Doctor / client phone
                "id": "wamid.demo.test.1",
                "type": "text",
                "text": {"body": "Hola, quería saber si tienen turnos para mañana a las 11"}
            }]
        }
        with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
             patch("app.services.brain.generate_ai_response", new_callable=AsyncMock) as mock_ai:
            mock_ai.return_value = ("¡Hola! Te dejo agendado para mañana a las 11:00 hs.", True, "mañana a las 11:00 hs")
            res = client.post("/webhook", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "success"
            # Verify send_whatsapp_message was called
            calls = [call.kwargs for call in mock_send.call_args_list]
            boss_alerts = [c for c in calls if "NUEVO TURNO AGENDADO" in c.get("text", "") or "INTERACCIÓN EN VIVO" in c.get("text", "")]
            assert len(boss_alerts) >= 1
            assert "CONSULTORIO MÉDICO" in boss_alerts[0]["text"]
            assert "5493439998877" in boss_alerts[0]["text"]
    finally:
        live_demo_service.reset_demo_mode()
