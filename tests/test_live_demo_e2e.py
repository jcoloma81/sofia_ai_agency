import pytest
import io
import openpyxl
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from main import app
from app.database import get_db
from app.models.prospect import Prospect
from app.config.settings import settings
from app.services.boss_mode import process_boss_message, LAST_ONBOARDED_CLIENT
from app.services.catalog import catalog_service
from tests.conftest import TestingSessionLocal

@pytest.fixture
def db():
    session = TestingSessionLocal()
    LAST_ONBOARDED_CLIENT.clear()
    try:
        yield session
    finally:
        LAST_ONBOARDED_CLIENT.clear()
        session.query(Prospect).delete()
        session.commit()
        session.close()

def test_full_street_demo_e2e_flow(db):
    """
    End-to-End Simulation of the 5-Step Live Street Demo in Ricardo's Shop:
    - Paso 0: Boss registers 'Ferretería Nogoyá' (Ricardo).
    - Paso 1: Boss dispatches live demo to Ricardo with 4 martillos & 2 alicates.
    - Paso 2: Ricardo asks for prices from his phone -> Gets base prices.
    - Paso 3: Boss sends supplier price increase Excel (+20%) -> Ricardo asks again -> Gets $17.400.
    - Paso 4: Ricardo sends order to Distribuidora Alem (Javier) -> Javier receives Remito PDF + template.
    """
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    # Pre-setup Distribuidora Alem in DB pointing to Javier's phone
    alem = Prospect(
        name="Distribuidora Alem",
        contact_name="Javier (Distribuidora Alem)",
        phone=settings.WHATSAPP_ALERT_PHONE,
        city="Paraná",
        campaign="supplier",
        status="supplier"
    )
    db.add(alem)
    db.commit()

    with patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tpl, \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:

        # ----------------------------------------------------
        # PASO 0: ALTA FLASH EN BASE DE DATOS (MODO JEFE - JAVIER)
        # ----------------------------------------------------
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        handled_p0, reply_p0, action_p0 = loop.run_until_complete(
            process_boss_message(
                db,
                settings.WHATSAPP_ALERT_PHONE,
                "Sofía, cargar cliente Ferretería Nogoyá, titular Ricardo, teléfono 3435112233"
            )
        )
        assert handled_p0 is True
        assert action_p0 == "client_onboarded"
        assert "Ferretería Nogoyá" in reply_p0
        assert "Ricardo" in reply_p0
        assert "5493435112233" in reply_p0
        assert LAST_ONBOARDED_CLIENT.get("phone") == "5493435112233"
        assert LAST_ONBOARDED_CLIENT.get("business_name") == "Ferretería Nogoyá"

        # ----------------------------------------------------
        # PASO 1: DISPARO DE LA DEMO EN FRÍO (PLANTILLA A A RICARDO)
        # ----------------------------------------------------
        handled_p1, reply_p1, action_p1 = loop.run_until_complete(
            process_boss_message(
                db,
                settings.WHATSAPP_ALERT_PHONE,
                "Sofía, mandale la demo a Ricardo con 4 martillos y 2 alicates"
            )
        )
        assert handled_p1 is True
        assert action_p1 == "kiosk_order_dispatched"
        assert "Ricardo" in reply_p1
        assert "5493435112233" in reply_p1

        # Verify demo was dispatched to Ricardo's phone
        dispatched_phones = [call[1]["to_phone"] for call in mock_msg.call_args_list]
        assert "5493435112233" in dispatched_phones
        mock_doc.assert_called()

        # ----------------------------------------------------
        # PASO 2: RESPUESTA Y COTIZACIÓN BASE (RICARDO PREGUNTA PRECIOS)
        # ----------------------------------------------------
        p2_payload = {
            "phone": "5493435112233",
            "message": "Hola Sofía, a cuánto tenés los martillos y los alicates?",
            "complex_name": "Ferretería Nogoyá",
            "contact_name": "Ricardo",
            "city": "Nogoyá"
        }
        res_p2 = client.post("/webhook", json=p2_payload)
        assert res_p2.status_code == 200
        data_p2 = res_p2.json()
        assert data_p2["status"] == "success"
        # Must quote catalog products
        assert any(k in data_p2["reply"].lower() for k in ["martillo", "alicate", "$"])

        # ----------------------------------------------------
        # PASO 3: ACTUALIZACIÓN DE PRECIOS EN VIVO (+20%)
        # ----------------------------------------------------
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Lista Precios"
        ws.append(["Código", "Descripción", "Precio"])
        ws.append(["FER-001", "Martillo galponero mango fibra 500g", 17400])
        ws.append(["FER-002", "Alicate corte diagonal 6 pulgadas", 13200])
        buf = io.BytesIO()
        wb.save(buf)
        excel_bytes = buf.getvalue()

        upd_res = catalog_service.update_from_supplier_excel(
            content=excel_bytes,
            filename="lista_proveedor_aumento.xlsx",
            supplier_name="Distribuidora Mayorista"
        )
        assert upd_res["status"] == "success"
        assert upd_res["matched_count"] >= 1

        # Ricardo asks again after price increase
        p3_payload = {
            "phone": "5493435112233",
            "message": "Y a cuánto se fue el martillo?",
            "complex_name": "Ferretería Nogoyá",
            "contact_name": "Ricardo"
        }
        res_p3 = client.post("/webhook", json=p3_payload)
        assert res_p3.status_code == 200
        data_p3 = res_p3.json()
        assert data_p3["status"] == "success"
        assert "17.400" in data_p3["reply"] or "17400" in data_p3["reply"]

        # ----------------------------------------------------
        # PASO 4: EL PASE DE GOL AL MAYORISTA (SIMULACIÓN ALEM -> JAVIER)
        # ----------------------------------------------------
        mock_msg.reset_mock()
        mock_doc.reset_mock()

        p4_payload = {
            "phone": "5493435112233",
            "message": "Sofi, mandale el pedido a Distribuidora Alem con 4 martillos y 2 alicates",
            "complex_name": "Ferretería Nogoyá",
            "contact_name": "Ricardo"
        }
        res_p4 = client.post("/webhook", json=p4_payload)
        assert res_p4.status_code == 200
        data_p4 = res_p4.json()
        assert data_p4["status"] == "success"
        assert data_p4["action"] == "kiosk_order_dispatched"
        assert "Distribuidora Alem" in data_p4["reply"]
        assert settings.WHATSAPP_ALERT_PHONE in data_p4["reply"]

        # Verify Javier's phone received the order & PDF remito
        mock_msg.assert_called()
        p4_dispatched_phones = [call[1]["to_phone"] for call in mock_msg.call_args_list]
        assert settings.WHATSAPP_ALERT_PHONE in p4_dispatched_phones
        mock_doc.assert_called()
