import pytest
from app.services.boss_mode import is_boss_number, process_boss_message
from app.config.settings import settings
from app.models.prospect import Prospect
from tests.conftest import TestingSessionLocal

@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.query(Prospect).delete()
        session.commit()
        session.close()

def test_is_boss_number():
    boss_phone = settings.WHATSAPP_ALERT_PHONE
    assert is_boss_number(boss_phone) is True
    assert is_boss_number("5493434536447") is True
    assert is_boss_number("5491112223344") is False

@pytest.mark.asyncio
async def test_boss_metrics_summary(db):
    # Add dummy lead
    lead = Prospect(
        phone="5493435112233",
        name="Comercio Test",
        status="meeting_scheduled"
    )
    db.add(lead)
    db.commit()

    handled, reply, action = await process_boss_message(db, settings.WHATSAPP_ALERT_PHONE, "resumen de hoy")
    assert handled is True
    assert action == "boss_metrics"
    assert "REPORTE EJECUTIVO" in reply
    assert "Citas agendadas" in reply
    assert "Catálogo" in reply

@pytest.mark.asyncio
async def test_boss_pause_and_activate(db):
    lead = Prospect(
        phone="5493435998877",
        name="Almacén San José",
        status="in_conversation"
    )
    db.add(lead)
    db.commit()

    # 1. Pause
    handled, reply, action = await process_boss_message(db, settings.WHATSAPP_ALERT_PHONE, "pausar 5998877")
    assert handled is True
    assert action == "human_takeover_set"
    assert "silenciada" in reply
    db.refresh(lead)
    assert lead.status == "human_takeover"

    # 2. Reactivate
    handled, reply, action = await process_boss_message(db, settings.WHATSAPP_ALERT_PHONE, "activar 5998877")
    assert handled is True
    assert action == "lead_reactivated"
    assert "Reactivé" in reply
    db.refresh(lead)
    assert lead.status == "in_conversation"

    # 3. Natural Language Pause without number ("lo tomo yo")
    handled, reply, action = await process_boss_message(db, settings.WHATSAPP_ALERT_PHONE, "lo tomo yo")
    assert handled is True
    assert action == "human_takeover_set"
    assert "silenciada" in reply
    db.refresh(lead)
    assert lead.status == "human_takeover"

    # 4. Reactivate without number ("activar")
    handled, reply, action = await process_boss_message(db, settings.WHATSAPP_ALERT_PHONE, "activar")
    assert handled is True
    assert action == "lead_reactivated"
    assert "Reactivé" in reply
    db.refresh(lead)
    assert lead.status == "in_conversation"


@pytest.mark.asyncio
async def test_boss_catalog_check(db):
    handled, reply, action = await process_boss_message(db, settings.WHATSAPP_ALERT_PHONE, "mostrar catálogo")
    assert handled is True
    assert action == "catalog_view"
    assert "CATÁLOGO" in reply

@pytest.mark.asyncio
async def test_boss_directive_set(db):
    handled, reply, action = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofía, el mínimo para flete gratis es 50.000 pesos y repartimos en zona centro"
    )
    assert handled is True
    assert action == "boss_directive_set"
    assert "Directiva comercial configurada con éxito" in reply
    assert "50.000" in reply

@pytest.mark.asyncio
async def test_boss_order_demo_with_words(db):
    handled, reply, action = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofía, anótame tres cajas de aceite y dos fardos de harina."
    )
    assert handled is True
    assert action == "boss_order_test"
    assert "DEMO EN VIVO" in reply
    assert "Aceite Cañuelas" in reply
    assert "Harina Pureza" in reply
    assert ("$76.400" in reply or "$68.200" in reply)

@pytest.mark.asyncio
async def test_boss_price_list_demo(db):
    from unittest.mock import patch, AsyncMock
    with patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:
        handled, reply, action = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Hola Sofía, mandame la lista de precios actualizada"
        )
        assert handled is True
        assert action == "boss_price_list_demo"
        assert "ENVÍO DE LISTA" in reply
        assert "archivo de Excel" in reply
        mock_doc.assert_called_once()
        call_kwargs = mock_doc.call_args[1]
        assert "catalogo_actualizado.xlsx" in call_kwargs["document_url"]
        assert call_kwargs["filename"] == "Lista_Precios_Distribuidora.xlsx"

@pytest.mark.asyncio
async def test_boss_order_confirmation_triggers_depot_alert(db):
    from unittest.mock import patch, AsyncMock
    with patch("app.services.whatsapp.notify_owner_order_confirmed", new_callable=AsyncMock) as mock_depot:
        handled, reply, action = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Si lo confirmo"
        )
        assert handled is True
        assert action == "boss_confirm_test"
        assert "PEDIDO CONFIRMADO" in reply
        mock_depot.assert_called_once()

@pytest.mark.asyncio
async def test_boss_conversational_chat(db):
    handled, reply, action = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Hola Sofía, ¿estás lista para trabajar hoy?"
    )
    assert handled is True
    assert action in ["boss_chat", "boss_chat_fallback"]
    assert len(reply) > 5
    # Must NEVER contain the robotic menu!
    assert "Estoy activa y monitoreando todos los canales. Podés pedirme:" not in reply

@pytest.mark.asyncio
async def test_boss_audio_stutter_inquiry(db):
    handled, reply, action = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "ml para para pedirte y bien necesitar fideo del más económico que tengas"
    )
    assert handled is True
    assert action in ["boss_product_inquiry", "boss_chat"]
    # Must NEVER generate the broken robotic template with stutters!
    assert "para para pedirte" not in reply
    assert "ml" not in reply
    assert "fideo" in reply.lower()



