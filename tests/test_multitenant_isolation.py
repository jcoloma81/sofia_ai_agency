import pytest
import os
import json
from unittest.mock import patch, AsyncMock
from app.models.prospect import Prospect, SupplierDraftOrder, MerchantProduct
from app.services.boss_mode import (
    process_boss_message,
    get_supplier_draft,
    clear_supplier_draft,
    add_items_to_supplier_draft,
    load_supplier_drafts,
)
from app.services.catalog import catalog_service, ProductItem


@pytest.mark.asyncio
async def test_multitenant_supplier_isolation(db):
    """
    Verifies that two distinct merchants can register suppliers with the same name,
    each with distinct contact phone numbers, without collision or cross-visibility.
    """
    merchant_a = "5493435111111"
    merchant_b = "5493435222222"

    # Merchant A registers Distribuidora Central
    handled_a, reply_a, action_a = await process_boss_message(
        db,
        merchant_a,
        "Sofi, agendá al proveedor Distribuidora Central al 3434110000"
    )
    assert handled_a is True
    assert action_a == "supplier_registered"

    # Merchant B registers Distribuidora Central with a different number
    handled_b, reply_b, action_b = await process_boss_message(
        db,
        merchant_b,
        "Sofi, agendá al proveedor Distribuidora Central al 3434220000"
    )
    assert handled_b is True
    assert action_b == "supplier_registered"

    # Verify both records exist in DB under their respective merchant phones
    sup_a = db.query(Prospect).filter(
        Prospect.merchant_phone == merchant_a,
        Prospect.name == "Distribuidora Central"
    ).first()
    sup_b = db.query(Prospect).filter(
        Prospect.merchant_phone == merchant_b,
        Prospect.name == "Distribuidora Central"
    ).first()

    assert sup_a is not None
    assert sup_a.phone == "5493434110000"
    assert sup_b is not None
    assert sup_b.phone == "5493434220000"

    # Merchant A asks for suppliers list -> only sees 3434110000
    handled_la, reply_la, action_la = await process_boss_message(
        db,
        merchant_a,
        "Sofi, proveedores"
    )
    assert handled_la is True
    assert "3434110000" in reply_la
    assert "3434220000" not in reply_la

    # Merchant B asks for suppliers list -> only sees 3434220000
    handled_lb, reply_lb, action_lb = await process_boss_message(
        db,
        merchant_b,
        "Sofi, proveedores"
    )
    assert handled_lb is True
    assert "3434220000" in reply_lb
    assert "3434110000" not in reply_lb


@pytest.mark.asyncio
async def test_multitenant_basket_draft_isolation(db):
    """
    Verifies that open purchase drafts/baskets are strictly isolated per merchant.
    Merchant A's items never leak to Merchant B, even for identical supplier names.
    """
    merchant_a = "5493435111111"
    merchant_b = "5493435222222"

    clear_supplier_draft("Distribuidora Central", merchant_phone=merchant_a, db=db)
    clear_supplier_draft("Distribuidora Central", merchant_phone=merchant_b, db=db)

    # Register supplier for Merchant A and Merchant B
    db.add(Prospect(name="Distribuidora Central", phone="5493434110000", merchant_phone=merchant_a, campaign="supplier", status="supplier"))
    db.add(Prospect(name="Distribuidora Central", phone="5493434220000", merchant_phone=merchant_b, campaign="supplier", status="supplier"))
    db.commit()

    # Merchant A adds tornillos to basket
    handled_a, reply_a, action_a = await process_boss_message(
        db,
        merchant_a,
        "Sofi, anotá para Distribuidora Central 10 cajas de tornillos"
    )
    assert handled_a is True
    assert action_a == "basket_item_added"
    assert "tornillos" in reply_a.lower()

    # Merchant B adds bolsas de cal to basket
    handled_b, reply_b, action_b = await process_boss_message(
        db,
        merchant_b,
        "Sofi, anotá para Distribuidora Central 5 bolsas de cal"
    )
    assert handled_b is True
    assert action_b == "basket_item_added"
    assert "cal" in reply_b.lower()

    # Query draft directly for Merchant A
    draft_a = get_supplier_draft("Distribuidora Central", merchant_phone=merchant_a, db=db)
    assert draft_a is not None
    items_a = [it["product_name"].lower() for it in draft_a["items"]]
    assert any("tornillos" in i for i in items_a)
    assert not any("cal" in i for i in items_a)

    # Query draft directly for Merchant B
    draft_b = get_supplier_draft("Distribuidora Central", merchant_phone=merchant_b, db=db)
    assert draft_b is not None
    items_b = [it["product_name"].lower() for it in draft_b["items"]]
    assert any("cal" in i for i in items_b)
    assert not any("tornillos" in i for i in items_b)

    # Conversational inquiry: Merchant A asks "que tengo anotado para Distribuidora Central"
    h_ia, rep_ia, act_ia = await process_boss_message(
        db,
        merchant_a,
        "Sofi, que tengo anotado para Distribuidora Central"
    )
    assert h_ia is True
    assert "tornillos" in rep_ia.lower()
    assert "cal" not in rep_ia.lower()

    # Conversational inquiry: Merchant B asks "que tengo anotado para Distribuidora Central"
    h_ib, rep_ib, act_ib = await process_boss_message(
        db,
        merchant_b,
        "Sofi, que tengo anotado para Distribuidora Central"
    )
    assert h_ib is True
    assert "cal" in rep_ib.lower()
    assert "tornillos" not in rep_ib.lower()


@pytest.mark.asyncio
async def test_multitenant_supplier_deletion_isolation(db):
    """
    Verifies that when Merchant A deletes a supplier, Merchant B's supplier record
    and open draft basket remain 100% untouched.
    """
    merchant_a = "5493435111111"
    merchant_b = "5493435222222"

    # Register supplier and basket for both merchants
    db.add(Prospect(name="Distribuidora Central", phone="5493434110000", merchant_phone=merchant_a, campaign="supplier", status="supplier"))
    db.add(Prospect(name="Distribuidora Central", phone="5493434220000", merchant_phone=merchant_b, campaign="supplier", status="supplier"))
    db.commit()

    add_items_to_supplier_draft("Distribuidora Central", [{"product_name": "Tornillos", "quantity": 10}], merchant_phone=merchant_a, db=db)
    add_items_to_supplier_draft("Distribuidora Central", [{"product_name": "Bolsas de cal", "quantity": 5}], merchant_phone=merchant_b, db=db)

    # Merchant A deletes Distribuidora Central
    handled_del, reply_del, action_del = await process_boss_message(
        db,
        merchant_a,
        "Sofi, eliminar proveedor Distribuidora Central"
    )
    assert handled_del is True
    assert action_del == "supplier_deleted"

    # Merchant A's record is gone from DB
    deleted_a = db.query(Prospect).filter(
        Prospect.merchant_phone == merchant_a,
        Prospect.name == "Distribuidora Central"
    ).first()
    assert deleted_a is None

    # Merchant A's draft is cleared
    draft_a = get_supplier_draft("Distribuidora Central", merchant_phone=merchant_a, db=db)
    assert draft_a is None

    # CRITICAL: Merchant B's supplier is STILL in DB!
    b_record = db.query(Prospect).filter(
        Prospect.merchant_phone == merchant_b,
        Prospect.name == "Distribuidora Central"
    ).first()
    assert b_record is not None
    assert b_record.phone == "5493434220000"

    # CRITICAL: Merchant B's draft is STILL intact!
    draft_b = get_supplier_draft("Distribuidora Central", merchant_phone=merchant_b, db=db)
    assert draft_b is not None
    assert len(draft_b["items"]) > 0


@pytest.mark.asyncio
async def test_multitenant_catalog_and_price_isolation(db):
    """
    Verifies that product catalogs and price lists uploaded by one merchant
    remain completely isolated and do not contaminate other merchants.
    """
    merchant_a = "5493435111111"
    merchant_b = "5493435222222"

    # Save isolated products for Merchant A
    prods_a = [
        ProductItem(name="Amoladora Angular 115mm", price=45000.0, presentation="Unidad", supplier="Herramientas Norte", category="Maquinaria"),
        ProductItem(name="Disco de Corte 115mm", price=1200.0, presentation="Unidad", supplier="Herramientas Norte", category="Abrasivos")
    ]
    catalog_service.save_merchant_products(prods_a, merchant_phone=merchant_a, supplier_name="Herramientas Norte", db=db)

    # Save isolated products for Merchant B (different supplier and higher prices)
    prods_b = [
        ProductItem(name="Amoladora Angular 115mm", price=58000.0, presentation="Unidad", supplier="Bazar Industrial Sur", category="Maquinaria"),
        ProductItem(name="Disco de Corte 115mm", price=1600.0, presentation="Unidad", supplier="Bazar Industrial Sur", category="Abrasivos")
    ]
    catalog_service.save_merchant_products(prods_b, merchant_phone=merchant_b, supplier_name="Bazar Industrial Sur", db=db)

    # Merchant A finds product
    p_a = catalog_service.find_product_exact_or_best("amoladora angular", merchant_phone=merchant_a, db=db)
    assert p_a is not None
    assert p_a.price == 45000.0
    assert p_a.supplier == "Herramientas Norte"

    # Merchant B finds product
    p_b = catalog_service.find_product_exact_or_best("amoladora angular", merchant_phone=merchant_b, db=db)
    assert p_b is not None
    assert p_b.price == 58000.0
    assert p_b.supplier == "Bazar Industrial Sur"

    # Price inquiry via boss message:
    h_a, r_a, act_a = await process_boss_message(db, merchant_a, "cuanto sale la amoladora angular")
    assert h_a is True
    assert "45.000" in r_a or "45000" in r_a
    assert "58.000" not in r_a

    h_b, r_b, act_b = await process_boss_message(db, merchant_b, "cuanto sale la amoladora angular")
    assert h_b is True
    assert "58.000" in r_b or "58000" in r_b
    assert "45.000" not in r_b


@pytest.mark.asyncio
async def test_multitenant_order_dispatch_routing(db):
    """
    Verifies that order dispatching routes the PDF order and WhatsApp message
    to the correct supplier phone configured by THAT specific merchant.
    """
    merchant_b = "5493435222222"

    # Register supplier and basket for Merchant B
    db.add(Prospect(name="Distribuidora Central", phone="5493434220000", merchant_phone=merchant_b, campaign="supplier", status="supplier"))
    db.commit()

    add_items_to_supplier_draft("Distribuidora Central", [{"product_name": "Bolsas de cal", "quantity": 5}], merchant_phone=merchant_b, db=db)

    with patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tpl, \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:

        # Merchant B dispatches their open order for Distribuidora Central
        handled, reply, action = await process_boss_message(
            db,
            merchant_b,
            "Sofi, mandale el pedido a Distribuidora Central"
        )
        assert handled is True
        assert action == "kiosk_order_dispatched"
        assert "¡Pedido despachado con éxito!" in reply
        assert "5493434220000" in reply  # Merchant B's supplier phone!

        # Verify dispatched calls
        mock_msg.assert_called()
        order_msgs = [c[1] for c in mock_msg.call_args_list if c[1]["to_phone"] == "5493434220000"]
        assert len(order_msgs) >= 1

        mock_doc.assert_called_once()
        assert mock_doc.call_args[1]["to_phone"] == "5493434220000"

        # Merchant B's draft is now cleared
        draft_b = get_supplier_draft("Distribuidora Central", merchant_phone=merchant_b, db=db)
        assert draft_b is None
