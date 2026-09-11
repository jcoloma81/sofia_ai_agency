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
    # 1. Register supplier
    handled, reply, action = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, agendá al proveedor Bulonera del Litoral al 3434536447 que nos vende tornillos"
    )
    assert handled is True
    assert action == "supplier_registered"
    assert "PROVEEDOR REGISTRADO CON ÉXITO" in reply
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

    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:
        
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

        mock_msg.assert_called_once()
        assert mock_msg.call_args[1]["to_phone"] == "5493434536447"
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
