import pytest
from app.services.boss_mode import is_boss_number, process_boss_message, LAST_ONBOARDED_CLIENT, LAST_BOSS_ORDERS
from app.config.settings import settings
from app.models.prospect import Prospect
from tests.conftest import TestingSessionLocal

@pytest.fixture
def db():
    session = TestingSessionLocal()
    LAST_ONBOARDED_CLIENT.clear()
    LAST_BOSS_ORDERS.clear()
    try:
        yield session
    finally:
        LAST_ONBOARDED_CLIENT.clear()
        LAST_BOSS_ORDERS.clear()
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

@pytest.mark.asyncio
async def test_boss_lista_completa(db):
    from unittest.mock import patch, AsyncMock
    with patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:
        handled, reply, action = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Hola Sofía, mandame la lista completa"
        )
        assert handled is True
        assert action == "boss_price_list_demo"
        assert "ENVÍO DE LISTA" in reply
        mock_doc.assert_called_once()

@pytest.mark.asyncio
async def test_boss_kiosk_order_dispatch(db):
    from unittest.mock import patch, AsyncMock
    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:
        handled, reply, action = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Sofi, mandale el pedido a Distribuidora San Martín al 3434536447 con 10 bolsas de harina y 5 cajas de aceite"
        )
        assert handled is True
        assert action == "kiosk_order_dispatched"
        assert "¡Pedido despachado con éxito!" in reply
        assert "Distribuidora San Martín" in reply
        mock_msg.assert_called_once()
        mock_doc.assert_called_once()

@pytest.mark.asyncio
async def test_boss_ferreteria_order_dispatch(db):
    from unittest.mock import patch, AsyncMock
    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:
        handled, reply, action = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Sofi, mandale el pedido a Ferretería Industrial Ricardo al 3434536447 con 5 cajas de tornillos autoperforantes y 2 discos de corte"
        )
        assert handled is True
        assert action == "kiosk_order_dispatched"
        assert "¡Pedido despachado con éxito!" in reply
        assert "Ferretería Industrial Ricardo" in reply
        assert "Tornillos autoperforantes" in reply
        mock_msg.assert_called_once()
        mock_doc.assert_called_once()

@pytest.mark.asyncio
async def test_boss_switch_rubro_ferreteria(db):
    handled, reply, action = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "rubro ferreteria"
    )
    assert handled is True
    assert action == "rubro_switched"
    assert "MODO FERRETERIA ACTIVADO" in reply
    assert "Ferretería & Bazar Industrial" in reply

@pytest.mark.asyncio
async def test_boss_dispatch_needs_phone(db):
    handled, reply, action = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, mandale el pedido a Ferretería Ricardo con 5 cajas de tornillos"
    )
    assert handled is True
    assert action == "dispatch_needs_phone"
    assert "Ricardo" in reply
    assert "número de teléfono" in reply

@pytest.mark.asyncio
async def test_boss_enviale_este_mensaje_con_los_pedidos(db):
    from unittest.mock import patch, AsyncMock
    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:
        handled, reply, action = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Enviale este mensaje con los pedidos de 5 cajas de tornillos a ferreteria nogoyá, el numero es 3434536447"
        )
        assert handled is True
        assert action == "kiosk_order_dispatched"
        assert "¡Pedido despachado con éxito!" in reply
        assert "Ferretería Nogoyá" in reply or "ferreteria nogoyá" in reply.lower()
        mock_msg.assert_called_once()
        mock_doc.assert_called_once()


@pytest.mark.asyncio
async def test_boss_client_onboarding_audio_text(db):
    handled, reply, action = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, cargá este cliente: Ferretería Nogoyá de Ricardo, teléfono 343 4556679, rubro ferretería, calle Nogoyá 450"
    )
    assert handled is True
    assert action == "client_onboarded"
    assert "CLIENTE DADO DE ALTA CON ÉXITO" in reply
    assert "Ferretería Nogoyá" in reply
    assert "Ricardo" in reply
    assert "5493434556679" in reply
    assert "Ferretería" in reply

    # Verify DB
    p = db.query(Prospect).filter(Prospect.phone == "5493434556679").first()
    assert p is not None
    assert p.name == "Ferretería Nogoyá"
    assert p.contact_name == "Ricardo"
    assert p.business_type == "ferreteria"
    assert p.campaign == "client_onboarding"


@pytest.mark.asyncio
async def test_boss_dispatch_to_onboarded_client_without_repeating_phone(db):
    from unittest.mock import patch, AsyncMock
    # First onboard
    await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, cargá este cliente: Ferretería Nogoyá de Ricardo, teléfono 343 4556679, rubro ferretería"
    )

    # Now dispatch directly without dictating the phone number
    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:
        handled, reply, action = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Mandale a Ricardo el pedido de 4 martillos, 2 alicates y una caja de tornillos"
        )
        assert handled is True
        assert action == "kiosk_order_dispatched"
        assert "¡Pedido despachado con éxito!" in reply
        assert "5493434556679" in reply
        mock_msg.assert_called_once()
        msg_kwargs = mock_msg.call_args[1]
        assert msg_kwargs["to_phone"] == "5493434556679"
        mock_doc.assert_called_once()
        doc_kwargs = mock_doc.call_args[1]
        assert doc_kwargs["to_phone"] == "5493434556679"


@pytest.mark.asyncio
async def test_boss_send_price_list_to_client(db):
    from unittest.mock import patch, AsyncMock
    # First onboard
    await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "Sofi, cargá este cliente: Ferretería Nogoyá de Ricardo, teléfono 343 4556679, rubro ferretería"
    )

    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_document", new_callable=AsyncMock) as mock_doc:
        handled, reply, action = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Mandale la lista de precios a Ricardo"
        )
        assert handled is True
        assert action == "boss_price_list_sent_client"
        assert "Lista de precios enviada con éxito" in reply
        assert "5493434556679" in reply
        mock_msg.assert_called_once()
        assert mock_msg.call_args[1]["to_phone"] == "5493434556679"
        mock_doc.assert_called_once()
        assert mock_doc.call_args[1]["to_phone"] == "5493434556679"


@pytest.mark.asyncio
async def test_manual_features_and_keywords_content():
    from app.services.boss_mode import get_client_manual_text
    manual = get_client_manual_text()
    assert "Ahorro inteligente" in manual
    assert "Despacho directo" in manual
    assert "5 PALABRAS CLAVE QUE PODÉS ESCRIBIRME CUANDO QUIERAS" in manual
    assert "manual" in manual
    assert "dudas" in manual
    assert "resumen" in manual
    assert "proveedores" in manual
    assert "empleados" in manual


@pytest.mark.asyncio
async def test_client_onboarding_welcome_message_includes_keywords(db):
    from unittest.mock import patch, AsyncMock
    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tpl:
        handled, reply, action = await process_boss_message(
            db,
            settings.WHATSAPP_ALERT_PHONE,
            "Sofi, cargá este cliente: Kiosco Belgrano de Laura, teléfono 343 4112233, rubro kiosco"
        )
        assert handled is True
        assert action == "client_onboarded"
        # Check welcome text sent to merchant
        mock_msg.assert_called()
        welcome_call = [c for c in mock_msg.call_args_list if c[1].get("to_phone") == "5493434112233"]
        assert len(welcome_call) > 0
        welcome_text = welcome_call[0][1]["text"]
        assert "5 PALABRAS CLAVE QUE PODÉS ESCRIBIRME CUANDO QUIERAS" in welcome_text
        assert "manual" in welcome_text
        assert "dudas" in welcome_text
        assert "resumen" in welcome_text
        assert "proveedores" in welcome_text
        assert "empleados" in welcome_text


@pytest.mark.asyncio
async def test_merchant_resumen_command(db):
    merchant_phone = "5493434998877"
    # When merchant asks for resumen with empty baskets
    handled, reply, action = await process_boss_message(
        db,
        merchant_phone,
        "resumen"
    )
    assert handled is True
    assert action == "no_active_baskets"
    assert "No tenés pedidos pendientes" in reply

    # Boss asks for resumen -> receives boss metrics
    handled_b, reply_b, action_b = await process_boss_message(
        db,
        settings.WHATSAPP_ALERT_PHONE,
        "resumen"
    )
    assert handled_b is True
    assert action_b == "boss_metrics"
    assert "REPORTE EJECUTIVO EN TIEMPO REAL" in reply_b


@pytest.mark.asyncio
async def test_employee_lifecycle_permissions_and_mirror_alert(db):
    from unittest.mock import patch, AsyncMock
    from app.services.boss_mode import add_items_to_supplier_draft

    merchant_phone = "5493434112244"
    employee_phone = "5493434536448"

    # Setup owner merchant
    owner = Prospect(
        phone=merchant_phone,
        name="Supermercado Don Pepe",
        contact_name="Pepe",
        business_type="almacen",
        status="active",
    )
    db.add(owner)

    supplier = Prospect(
        phone="5493434999999",
        name="Molinos",
        contact_name="Carlos Molinos",
        business_type="proveedor",
        campaign="supplier",
        merchant_phone=merchant_phone,
        status="active",
    )
    db.add(supplier)
    db.commit()

    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tpl:

        # 1. Owner adds Lucas as employee
        handled, reply, action = await process_boss_message(
            db,
            merchant_phone,
            f"Sofi, agregá a Lucas como empleado al {employee_phone}"
        )
        assert handled is True
        assert action == "employee_added"
        assert "Lucas" in reply
        assert "registrado con éxito" in reply

        # Check DB
        emp = db.query(Prospect).filter(Prospect.phone == employee_phone).first()
        assert emp is not None
        assert emp.parent_merchant_phone == merchant_phone
        assert emp.contact_name == "Lucas"
        assert emp.can_dispatch is False
        assert emp.employee_role == "repositor"

        # Check welcome WhatsApp sent to employee
        emp_calls = [c for c in mock_msg.call_args_list if c[1].get("to_phone") == employee_phone]
        assert len(emp_calls) > 0
        assert "¡Hola Lucas!" in emp_calls[0][1]["text"]

        # 2. Owner lists employees
        handled, reply, action = await process_boss_message(
            db,
            merchant_phone,
            "empleados"
        )
        assert handled is True
        assert action == "employees_list"
        assert "Lucas" in reply
        assert "Anotador" in reply or "Solo canasta" in reply

        # 3. Employee attempts dispatch while unauthorized -> blocked politely
        handled, reply, action = await process_boss_message(
            db,
            employee_phone,
            "Sofi, mandale el pedido a Molinos"
        )
        assert handled is True
        assert action == "employee_dispatch_unauthorized"
        assert "Acceso restringido" in reply
        assert "Lucas" in reply and "autoriz" in reply

        # 4. Owner authorizes employee
        handled, reply, action = await process_boss_message(
            db,
            merchant_phone,
            "Sofi, autorizá a Lucas a despachar pedidos"
        )
        assert handled is True
        assert action == "employee_dispatch_granted"
        assert "Lucas" in reply and "autorizado" in reply

        db.refresh(emp)
        assert emp.can_dispatch is True

        # 5. Add items to shared store draft for Molinos
        add_items_to_supplier_draft(
            "Molinos",
            [{"name": "Harina 000 1kg", "qty": 10, "price": 950.0}],
            merchant_phone=merchant_phone,
            db=db
        )

        # 6. Employee dispatches order -> succeeds + sends mirror alert to owner
        mock_msg.reset_mock()
        handled, reply, action = await process_boss_message(
            db,
            employee_phone,
            "Sofi, mandale el pedido a Molinos"
        )
        assert handled is True
        assert action == "kiosk_order_dispatched"
        assert "Pedido despachado con éxito" in reply

        # Verify owner received mirror alert notification
        owner_mirror_calls = [
            c for c in mock_msg.call_args_list 
            if c[1].get("to_phone") == merchant_phone and "NOTIFICACIÓN DE PEDIDO DESPACHADO (EQUIPO)" in c[1].get("text", "")
        ]
        assert len(owner_mirror_calls) > 0
        mirror_text = owner_mirror_calls[0][1]["text"]
        assert "Lucas" in mirror_text
        assert "Molinos" in mirror_text
        assert "Harina" in mirror_text

        # 7. Owner revokes dispatch permission
        handled, reply, action = await process_boss_message(
            db,
            merchant_phone,
            "Sofi, quitale el permiso a Lucas de despachar"
        )
        assert handled is True
        assert action == "employee_dispatch_revoked"
        assert "Lucas" in reply and "ya no puede" in reply

        db.refresh(emp)
        assert emp.can_dispatch is False

        # 8. Owner removes employee from team
        handled, reply, action = await process_boss_message(
            db,
            merchant_phone,
            "Sofi, eliminá al empleado Lucas"
        )
        assert handled is True
        assert action == "employee_deleted"
        assert "Empleado eliminado" in reply
        assert "Lucas" in reply and "dado de baja" in reply

        emp_deleted = db.query(Prospect).filter(Prospect.phone == employee_phone).first()
        assert emp_deleted is None


@pytest.mark.asyncio
async def test_employee_shared_basket_and_resumen(db):
    from app.services.boss_mode import add_items_to_supplier_draft

    merchant_phone = "5493434112255"
    employee_phone = "5493434536455"

    owner = Prospect(
        phone=merchant_phone,
        name="Autoservicio Centro",
        contact_name="Martín",
        business_type="almacen",
        status="active",
    )
    db.add(owner)
    db.commit()

    # Add employee directly
    emp = Prospect(
        phone=employee_phone,
        parent_merchant_phone=merchant_phone,
        name="Autoservicio Centro",
        contact_name="Rodrigo",
        employee_role="repositor",
        can_dispatch=False,
        status="active",
    )
    db.add(emp)
    db.commit()

    # Add items to store's draft under owner's phone
    add_items_to_supplier_draft(
        "Distribuidora Alem",
        [{"name": "Azúcar Ledesma 1kg", "qty": 20, "price": 800.0}],
        merchant_phone=merchant_phone,
        db=db
    )

    # Employee Rodrigo asks for "resumen"
    handled, reply, action = await process_boss_message(
        db,
        employee_phone,
        "resumen"
    )
    assert handled is True
    assert action == "all_baskets_summary"
    assert "Distribuidora Alem" in reply
    assert "Azúcar Ledesma" in reply




