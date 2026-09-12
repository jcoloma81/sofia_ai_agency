import pytest
import io
import os
import openpyxl
from unittest.mock import patch, AsyncMock
from app.config.settings import settings
from app.models.prospect import Prospect
from tests.conftest import TestingSessionLocal
from app.services.boss_mode import (
    process_boss_message,
    load_supplier_drafts,
    clear_supplier_draft,
    get_supplier_draft
)
from app.services.catalog import catalog_service, ProductItem

@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.query(Prospect).delete()
        session.commit()
        session.close()

@pytest.mark.asyncio
async def test_supplier_registration_and_listing(db):
    with patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock), \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock):
        # 1. Register supplier
        handled, reply, action = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Sofi, agendá al proveedor Bulonera del Litoral al 3434536447 que nos vende tornillos"
        )
        assert handled is True
        assert action == "supplier_registered"
        assert "PROVEEDOR REGISTRADO" in reply
        assert "Bulonera del Litoral" in reply
        assert "5493434536447" in reply

        # 2. List suppliers
        handled_l, reply_l, action_l = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Sofi, cuáles son mis proveedores?"
        )
        assert handled_l is True
        assert action_l == "suppliers_list"
        assert "Bulonera del Litoral" in reply_l
        assert "5493434536447" in reply_l


@pytest.mark.asyncio
async def test_supplier_baskets_and_inquiries(db):
    clear_supplier_draft("Bulonera del Litoral")
    clear_supplier_draft("Pinturas Litoral")

    # 1. Add items for Bulonera
    handled1, reply1, action1 = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, anotá para la Bulonera del Litoral 5 cajas de tornillos T1 y 2 alicates"
    )
    assert handled1 is True
    assert action1 == "basket_item_added"
    assert "Anotado en la canasta de Bulonera del Litoral" in reply1

    # 2. Add items for Pinturas Litoral
    handled2, reply2, action2 = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, para Pinturas Litoral anotame 3 latas de látex blanco"
    )
    assert handled2 is True
    assert action2 == "basket_item_added"
    assert "Anotado en la canasta de Pinturas Litoral" in reply2

    # 3. Check specific basket for Bulonera
    handled_b, reply_b, action_b = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, qué tengo para pedirle a la Bulonera del Litoral?"
    )
    assert handled_b is True
    assert action_b == "single_basket_detail"
    assert "BULONERA DEL LITORAL" in reply_b
    assert "tornillos" in reply_b.lower()

    # 4. Check all open baskets
    handled_all, reply_all, action_all = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, pedidos pendientes a proveedores"
    )
    assert handled_all is True
    assert action_all == "all_baskets_summary"
    assert "Bulonera del Litoral" in reply_all
    assert "Pinturas Litoral" in reply_all


@pytest.mark.asyncio
async def test_supplier_basket_dispatch_and_clearing(db):
    with patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tpl, \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:
        
        # Setup Bulonera supplier in DB
        await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Sofi, agendá al proveedor Bulonera del Litoral al 3434536447"
        )
        # Add items to basket
        await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Sofi, anotá para la Bulonera del Litoral 10 cajas de tornillos y 4 pinzas"
        )

        # Dispatch order using the basket items
        handled, reply, action = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Sofi, mandale el pedido a Bulonera del Litoral"
        )
        assert handled is True
        assert action == "kiosk_order_dispatched"
        assert "¡Pedido despachado con éxito!" in reply
        assert "vaciada y lista" in reply
        assert "5493434536447" in reply

        mock_msg.assert_called()
        # Find the order dispatch message
        order_msgs = [c[1] for c in mock_msg.call_args_list if c[1]["to_phone"] == "5493434536447" and ("pedido formal" in c[1]["text"].lower() or "remito" in c[1]["text"].lower())]
        assert len(order_msgs) >= 1
        mock_doc.assert_called_once()
        assert mock_doc.call_args[1]["to_phone"] == "5493434536447"

        # Verify basket is now empty
        basket_after = get_supplier_draft("Bulonera del Litoral")
        assert basket_after is None


def test_catalog_supplier_tagging_and_excel_export():
    catalog_service.set_rubro("ferreteria")
    
    # Create sample supplier Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lista Precios"
    ws.append(["Código", "Descripción", "Precio"])
    ws.append(["FER-001", "Martillo Galponero 20mm", 19500])
    ws.append(["BUL-999", "Tornillos Autoperforantes 100u", 8500])
    
    buf = io.BytesIO()
    wb.save(buf)
    content = buf.getvalue()

    result = catalog_service.update_from_supplier_excel(
        content,
        filename="lista_bulonera_marzo.xlsx",
        supplier_name="Bulonera del Litoral"
    )
    assert result["status"] == "success"
    assert "Bulonera del Litoral" in result["whatsapp_message"]

    # Verify supplier is tagged in catalog
    matched_prod = catalog_service.find_product_exact_or_best("Martillo Galponero 20mm")
    assert matched_prod is not None
    assert matched_prod.price == 19500
    assert matched_prod.supplier == "Bulonera del Litoral"

    # Verify export includes Proveedor column
    export_path = "assets/test_export_suppliers.xlsx"
    catalog_service.export_to_excel(export_path)
    
    wb_exp = openpyxl.load_workbook(export_path)
    ws_exp = wb_exp.active
    headers = [cell.value for cell in ws_exp[1]]
    assert "Proveedor" in headers
    
    if os.path.exists(export_path):
        os.remove(export_path)


def test_merchant_client_dispatch_to_distribuidora_alem_simulation(db):
    from fastapi.testclient import TestClient
    from main import app
    from app.database import get_db
    from app.services.boss_mode import LAST_ONBOARDED_CLIENT

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    # 1. Setup Distribuidora Alem with Javier's phone in DB
    alem = Prospect(
        name="Distribuidora Alem",
        contact_name="Javier (Distribuidora Alem)",
        phone="5493434536447",
        city="Paraná",
        campaign="supplier",
        status="supplier"
    )
    db.add(alem)

    # 2. Setup Ferretería Nogoyá as the active merchant client
    ferreteria = Prospect(
        name="Ferretería Nogoyá",
        contact_name="Ricardo",
        phone="5493435112233",
        city="Nogoyá",
        campaign="client_onboarding",
        status="in_conversation"
    )
    db.add(ferreteria)
    db.commit()

    LAST_ONBOARDED_CLIENT.clear()
    LAST_ONBOARDED_CLIENT.update({
        "phone": "5493435112233",
        "business_name": "Ferretería Nogoyá",
        "contact_name": "Ricardo",
        "business_type": "ferreteria",
        "city": "Nogoyá"
    })

    with patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tpl, \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:
        
        # Ricardo sends dispatch directive from his phone via webhook
        payload = {
            "phone": "5493435112233",
            "message": "Sofi, mandale el pedido a Distribuidora Alem con 4 martillos y 2 alicates",
            "complex_name": "Ferretería Nogoyá",
            "contact_name": "Ricardo",
            "city": "Nogoyá"
        }
        response = client.post("/webhook", json=payload)
        assert response.status_code == 200
        res = response.json()

        assert res["status"] == "success"
        assert res["action"] == "kiosk_order_dispatched"
        assert "Distribuidora Alem" in res["reply"]
        assert "5493434536447" in res["reply"]

        mock_msg.assert_called()
        dispatched_to_phones = [call[1]["to_phone"] for call in mock_msg.call_args_list]
        assert "5493434536447" in dispatched_to_phones
        assert "5493435112233" in dispatched_to_phones


def test_client_onboarding_5_options_and_quick_replies(db):
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)

    # 1. Setup client onboarding merchant
    merchant = Prospect(
        name="Ferretería El Triángulo",
        contact_name="Carlos",
        phone="5493436001122",
        city="Paraná",
        campaign="client_onboarding",
        status="in_conversation"
    )
    db.add(merchant)
    db.commit()

    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.notify_owner_demo_requested", new_callable=AsyncMock) as mock_demo_notify:

        # Test A: Menu repetition with 5 options
        resp = client.post("/webhook", json={
            "phone": "5493436001122",
            "message": "Hola Sofi"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("guided_menu") is True
        assert "catálogo de demostración" in data["reply"]
        assert "1️⃣" in data["reply"]
        assert "5️⃣" in data["reply"]
        assert "proveedores tengo registrados" in data["reply"]

        # Test B: Option 4 - How to upload / forward lists
        resp = client.post("/webhook", json={
            "phone": "5493436001122",
            "message": "4"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("catalog_instructions") is True
        assert "PDF o Excel" in data["reply"]

        # Test C: Option 5 - Registered suppliers query
        resp = client.post("/webhook", json={
            "phone": "5493436001122",
            "message": "¿Qué proveedores tengo registrados?"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("suppliers_summary") is True
        assert "PROVEEDORES Y LISTAS REGISTRADAS" in data["reply"]

        # Test D: Cold outreach quick reply - 'Ver demostración'
        lead = Prospect(
            name="Comercio Prospecto",
            contact_name="Martín",
            phone="5493436998877",
            city="Paraná",
            campaign="ai_agency",
            status="contacted"
        )
        db.add(lead)
        db.commit()

        resp = client.post("/webhook", json={
            "phone": "5493436998877",
            "message": "Ver demostración"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("demo_requested") is True
        mock_demo_notify.assert_called_once()

        # Test E: Cold outreach quick reply - 'Ahora no, gracias'
        resp = client.post("/webhook", json={
            "phone": "5493436998877",
            "message": "Ahora no, gracias"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("action") == "opt_out"


def test_merchant_client_register_supplier_with_auto_presentation(db):
    from fastapi.testclient import TestClient
    from main import app
    from app.database import get_db

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    # 1. Setup Kiosco Alameda as the merchant client
    kiosco = Prospect(
        name="Kiosco Alameda",
        contact_name="Marcelo",
        phone="5493435112233",
        city="Paraná",
        campaign="client_onboarding",
        status="in_conversation"
    )
    db.add(kiosco)
    db.commit()

    with patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tpl, \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg:
        mock_tpl.return_value = False

        # Marcelo instructs Sofia by text to register Carlos from Distribuidora El Progreso
        payload = {
            "phone": "5493435112233",
            "message": "Sofi, agendá al proveedor Distribuidora El Progreso al 3434536447"
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data.get("status") == "success"
        assert data.get("action") == "supplier_registered"
        assert "PROVEEDOR REGISTRADO Y CONTACTADO" in data["reply"]
        assert "Distribuidora El Progreso" in data["reply"]
        assert "5493434536447" in data["reply"]

        # Check DB
        sup_db = db.query(Prospect).filter(Prospect.phone == "5493434536447").first()
        assert sup_db is not None
        assert sup_db.name == "Distribuidora El Progreso"
        assert sup_db.business_type == "proveedor"
        assert sup_db.campaign == "supplier"

        # Check Meta Template dispatch to the supplier
        mock_tpl.assert_called_once()
        tpl_args = mock_tpl.call_args[1]
        assert tpl_args["to_phone"] == "5493434536447"
        assert tpl_args["template_name"] == "presentacion_proveedor_v1"

        # Check conversational message to supplier
        dispatched_messages = [call[1] for call in mock_msg.call_args_list if call[1]["to_phone"] == "5493434536447"]
        assert len(dispatched_messages) >= 1
        intro_text = dispatched_messages[0]["text"]
        assert "Marcelo de Kiosco Alameda" in intro_text
        assert "lista de precios" in intro_text
        assert "Agendá este contacto" in intro_text
        assert "Agendado" in intro_text


def test_meta_contacts_vcard_registration(db):
    from fastapi.testclient import TestClient
    from main import app
    from app.database import get_db

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    # Setup merchant
    ferreteria = Prospect(
        name="Ferretería Nogoyá",
        contact_name="Ricardo",
        phone="5493435112233",
        campaign="client_onboarding",
        status="in_conversation"
    )
    db.add(ferreteria)
    db.commit()

    with patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tpl, \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg:

        # Simulate Meta Cloud API incoming contact payload
        meta_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "123456789",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "contacts": [{"profile": {"name": "Ricardo"}}],
                                "messages": [
                                    {
                                        "from": "5493435112233",
                                        "id": "wamid.contact.123",
                                        "timestamp": "1726000000",
                                        "type": "contacts",
                                        "contacts": [
                                            {
                                                "name": {
                                                    "first_name": "Carlos",
                                                    "formatted_name": "Carlos Molinos"
                                                },
                                                "phones": [
                                                    {
                                                        "phone": "+54 9 343 499-1122",
                                                        "type": "CELL"
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        resp = client.post("/webhook", json=meta_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("action") == "supplier_registered"

        # Check DB
        sup_db = db.query(Prospect).filter(Prospect.phone == "5493434991122").first()
        assert sup_db is not None
        assert sup_db.name in ["Carlos Molinos", "Molinos"]
        assert "Carlos" in (sup_db.contact_name or "")
        assert sup_db.business_type == "proveedor"


def test_client_manual_and_option_6_guidance(db):
    from fastapi.testclient import TestClient
    from main import app
    from app.database import get_db

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    kiosco = Prospect(
        name="Kiosco Alameda",
        contact_name="Marcelo",
        phone="5493435112233",
        campaign="client_onboarding",
        status="in_conversation"
    )
    db.add(kiosco)
    db.commit()

    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg:
        # 1. Ask for manual
        resp = client.post("/webhook", json={"phone": "5493435112233", "message": "manual"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("client_manual_sent") is True
        assert "Agendar proveedores nuevos en 1 toque" in data["reply"]
        assert "Sofía - Compras" in data["reply"]

        # 2. Ask for option 6
        resp = client.post("/webhook", json={"phone": "5493435112233", "message": "6"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("supplier_reg_guide") is True
        assert "CÓMO AGENDAR PROVEEDORES NUEVOS" in data["reply"]
        assert "Dictámelo por audio o texto" in data["reply"]
        assert "compartime su contacto de WhatsApp" in data["reply"]

        # 3. Menu greeting includes Option 6
        resp = client.post("/webhook", json={"phone": "5493435112233", "message": "hola"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("guided_menu") is True
        assert "6️⃣" in data["reply"]
        assert "agendá al proveedor" in data["reply"].lower() or "agendá a" in data["reply"].lower()



