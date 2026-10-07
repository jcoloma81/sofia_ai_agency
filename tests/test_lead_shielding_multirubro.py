import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.live_demo import live_demo_service
from app.services import brain
from app.services.brain import SYSTEM_PROMPT_AGENCY

@pytest.mark.asyncio
async def test_meta_ads_lead_gym_stays_agency_prompt():
    """
    Verifies that when a gym owner writes asking for a demo from Meta Ads,
    Sofia stays in SYSTEM_PROMPT_AGENCY mode and does NOT pretend to sell gym passes.
    """
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "¡Hola! Para gimnasios te ayudo a automatizar cobros de cuotas del 1 al 10, turnos de canchas y clases de prueba 24/7."}]
            }
        }]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_res

        reply, is_meeting, details = await brain.generate_ai_response(
            incoming_text="Hola, vi el anuncio en Instagram y quiero ver una demo para mi gimnasio",
            conversation_history=[],
            campaign="ai_agency",
            phone="5493439991111"
        )

        assert mock_post.called
        call_args = mock_post.call_args[1]
        payload = call_args["json"]
        system_instruction = payload["systemInstruction"]["parts"][0]["text"]

        # MUST contain agency instructions and MUST NOT contain Olimpo gym receptionist prompt
        assert "ASISTENTE COMERCIAL DE LA AGENCIA" in system_instruction
        assert "Centro de Entrenamiento & Fitness Olimpo" not in system_instruction
        assert "Pase Libre Musculación" not in system_instruction

@pytest.mark.asyncio
async def test_meta_ads_lead_consultorio_stays_agency_prompt():
    """
    Verifies that when a doctor writes asking how it works for a medical/dental clinic,
    Sofia stays in SYSTEM_PROMPT_AGENCY mode and does NOT pretend to be San Lucas receptionist.
    """
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "¡Hola doctor! Para consultorios me encargo de gestionar turnos 24/7 y reducir el ausentismo con recordatorios."}]
            }
        }]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_res

        reply, is_meeting, details = await brain.generate_ai_response(
            incoming_text="Hola, vi la publicidad en Facebook, ¿cómo funciona para un consultorio odontológico?",
            conversation_history=[],
            campaign="ai_agency",
            phone="5493439992222"
        )

        assert mock_post.called
        call_args = mock_post.call_args[1]
        payload = call_args["json"]
        system_instruction = payload["systemInstruction"]["parts"][0]["text"]

        assert "ASISTENTE COMERCIAL DE LA AGENCIA" in system_instruction
        assert "Consultorio Médico y Odontológico San Lucas" not in system_instruction

@pytest.mark.asyncio
async def test_meta_ads_lead_workshop_stays_agency_prompt():
    """
    Verifies that when an auto workshop owner writes,
    Sofia stays in SYSTEM_PROMPT_AGENCY mode and does NOT pretend to receive cars.
    """
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "¡Hola! Para talleres mecánicos coordino recepción de service y estados de entrega sin interrumpir el taller."}]
            }
        }]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_res

        reply, is_meeting, details = await brain.generate_ai_response(
            incoming_text="Hola, tengo un taller mecánico en Paraná, ¿cómo funciona el sistema de Sofía?",
            conversation_history=[],
            campaign="ai_agency",
            phone="5493439993333"
        )

        assert mock_post.called
        call_args = mock_post.call_args[1]
        payload = call_args["json"]
        system_instruction = payload["systemInstruction"]["parts"][0]["text"]

        assert "ASISTENTE COMERCIAL DE LA AGENCIA" in system_instruction
        assert "Taller Mecánico & Mantenimiento Integral Boxes" not in system_instruction

@pytest.mark.asyncio
async def test_active_demo_does_not_hijack_agency_inquiry():
    """
    Verifies that even if Javier activated '#demo consultorio' in memory,
    any lead asking about pricing, software or agency services receives SYSTEM_PROMPT_AGENCY.
    """
    live_demo_service.set_demo_mode("consultorio", duration_minutes=30)
    try:
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "El abono mensual es de $30.000 finales por mes."}]
                }
            }]
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_res

            reply, is_meeting, details = await brain.generate_ai_response(
                incoming_text="Hola, vi el anuncio en Instagram, ¿cuánto sale el abono mensual del servicio?",
                conversation_history=[],
                campaign="ai_agency",
                phone="5493439994444"
            )

            assert mock_post.called
            call_args = mock_post.call_args[1]
            payload = call_args["json"]
            system_instruction = payload["systemInstruction"]["parts"][0]["text"]

            # Must use agency prompt, NOT consultorio receptionist prompt
            assert "ASISTENTE COMERCIAL DE LA AGENCIA" in system_instruction
            assert "$30.000 finales" in system_instruction
            assert "recepcionista virtual del Consultorio" not in system_instruction
    finally:
        live_demo_service.reset_demo_mode()

@pytest.mark.asyncio
async def test_live_demo_still_works_for_actual_patient_query():
    """
    Verifies that when Javier DOES activate a live demo for a doctor meeting,
    an actual patient inquiry ('tienen vacunas para mi perro?') still routes to the demo prompt.
    """
    live_demo_service.set_demo_mode("veterinaria", duration_minutes=15)
    try:
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "¡Hola! Para vacunas tenemos turno hoy a las 17 hs."}]
                }
            }]
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_res

            reply, is_meeting, details = await brain.generate_ai_response(
                incoming_text="Hola, ¿tienen vacunas disponibles para mi perro hoy?",
                conversation_history=[],
                campaign="ai_agency",
                phone="5493439995555"
            )

            assert mock_post.called
            call_args = mock_post.call_args[1]
            payload = call_args["json"]
            system_instruction = payload["systemInstruction"]["parts"][0]["text"]

            assert "Veterinaria & Pet Shop Huellitas" in system_instruction
    finally:
        live_demo_service.reset_demo_mode()

@pytest.mark.asyncio
async def test_meta_ads_lead_other_province_remote_response():
    """
    Verifies that when a lead from Buenos Aires, Cordoba or another province writes,
    Sofia's instructions welcome them warmly with 100% cloud national remote setup.
    """
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "¡Qué bueno! Atendemos negocios en todo el país de forma 100% remota."}]
            }
        }]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_res

        reply, is_meeting, details = await brain.generate_ai_response(
            incoming_text="Hola, no soy de Paraná, tengo mi negocio en Buenos Aires, ¿me sirve el sistema?",
            conversation_history=[],
            campaign="ai_agency",
            phone="5491144445555"
        )

        assert mock_post.called
        call_args = mock_post.call_args[1]
        payload = call_args["json"]
        system_instruction = payload["systemInstruction"]["parts"][0]["text"]

        assert "en todo el país" in system_instruction
        assert "equipo de ventas" in system_instruction

@pytest.mark.asyncio
async def test_no_director_word_in_system_prompt():
    """
    Verifies that Sofia does NOT refer to Javier as 'director', but as team sales specialist,
    and prohibits mentioning personal names unsolicited.
    """
    assert "PROHIBIDO TERMINANTEMENTE usar la palabra \"director\"" in SYSTEM_PROMPT_AGENCY
    assert "CERO NOMBRES PERSONALES" in SYSTEM_PROMPT_AGENCY
    assert "alguien de nuestro equipo de ventas" in SYSTEM_PROMPT_AGENCY

