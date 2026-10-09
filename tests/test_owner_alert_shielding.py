import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone, timedelta

from app.services import whatsapp
from app.services.appointment_service import appointment_service
from app.models.tenant import Tenant, Appointment

@pytest.mark.asyncio
async def test_send_owner_or_admin_alert_template_success():
    """Verify that send_owner_or_admin_alert sends via approved Meta Template first."""
    with patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tmpl, \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg:

        mock_tmpl.return_value = True

        result = await whatsapp.send_owner_or_admin_alert(
            to_phone="5493434536447",
            fallback_text="Fallback text alert",
            business_name="Clínica Alvear",
            event_type="Cancelación de Turno",
            client_title="Juan Pérez (+549343111222)",
            details_summary="Turno del 15/10 16:30 hs cancelado."
        )

        assert result is True
        mock_tmpl.assert_called_once()
        call_kwargs = mock_tmpl.call_args.kwargs
        assert call_kwargs["to_phone"] == "5493434536447"
        assert "notificacion_operativa_v1" in [call_kwargs["template_name"], "alerta_nueva_cita_v1", "alerta_nueva_cita_v2"]
        assert call_kwargs["body_params"][0] == "Clínica Alvear"
        assert call_kwargs["body_params"][1] == "Cancelación de Turno"
        # Standard message should NOT be called since template succeeded
        mock_msg.assert_not_called()

@pytest.mark.asyncio
async def test_send_owner_or_admin_alert_fallback_to_text():
    """Verify that send_owner_or_admin_alert gracefully falls back to text if templates fail/pending."""
    with patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tmpl, \
         patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg:

        # All template candidates fail (e.g. pending review by Meta)
        mock_tmpl.return_value = False
        mock_msg.return_value = True

        result = await whatsapp.send_owner_or_admin_alert(
            to_phone="5493434536447",
            fallback_text="Fallback text alert",
            business_name="Sofía AI Agency",
            event_type="Reunión Confirmada",
            client_title="Berny",
            details_summary="Turno para la tarde"
        )

        assert result is True
        # Both templates tried, then fell back to message
        assert mock_tmpl.call_count >= 1
        mock_msg.assert_called_once_with(to_phone="5493434536447", text="Fallback text alert")

@pytest.mark.asyncio
async def test_notify_javier_meeting_scheduled_dual_channel():
    """Verify that Javier's appointment alerts use send_owner_or_admin_alert AND email."""
    with patch("app.services.whatsapp.send_owner_or_admin_alert", new_callable=AsyncMock) as mock_owner_alert, \
         patch("app.services.whatsapp.send_email_alert", new_callable=AsyncMock) as mock_email:

        mock_owner_alert.return_value = True
        mock_email.return_value = True

        await whatsapp.notify_javier_meeting_scheduled(
            prospect_name="Distribuidora Litoral",
            contact_name="Carlos",
            phone="5493434669544",
            city="Paraná",
            meeting_details="la tarde",
            last_message="De tarde",
            campaign="ai_agency"
        )

        mock_owner_alert.assert_called_once()
        owner_kwargs = mock_owner_alert.call_args.kwargs
        assert owner_kwargs["business_name"] == "Sofía AI Agency"
        assert owner_kwargs["event_type"] == "Reunión Confirmada"
        assert "Distribuidora Litoral" in owner_kwargs["client_title"]
        assert "la tarde" in owner_kwargs["details_summary"]

        mock_email.assert_called_once()
        email_kwargs = mock_email.call_args.kwargs
        assert "Cita Confirmada: Distribuidora Litoral" in email_kwargs["subject"]

@pytest.mark.asyncio
async def test_appointment_cancellation_triggers_owner_alert(db):
    """Verify that clinic appointment cancellation dispatches send_owner_or_admin_alert."""
    tenant = Tenant(
        slug="clinica_shield_test",
        name="Clínica Shield Dental",
        business_type="salud",
        owner_phone="5493434998877",
        owner_name="Dr. Ramos",
        modules_enabled='["turnos_rellena_huecos"]'
    )
    db.add(tenant)
    db.commit()

    apt = Appointment(
        tenant_id=tenant.id,
        patient_name="Ana Laura",
        patient_phone="5493434112233",
        appointment_date=datetime.now(timezone.utc) + timedelta(days=1),
        doctor_or_service="Odontología General",
        status="agendado"
    )
    db.add(apt)
    db.commit()

    with patch("app.services.whatsapp.send_owner_or_admin_alert", new_callable=AsyncMock) as mock_owner_alert, \
         patch("app.services.tenant_service.tenant_service.send_branded_notification", new_callable=AsyncMock):

        mock_owner_alert.return_value = True

        res = await appointment_service.cancel_and_fill_gap(db, apt.id, reason="Imprevisto laboral")

        assert res["status"] == "success"
        mock_owner_alert.assert_called_once()
        owner_kwargs = mock_owner_alert.call_args.kwargs
        assert owner_kwargs["to_phone"] == "5493434998877"
        assert owner_kwargs["business_name"] == "Clínica Shield Dental"
        assert owner_kwargs["event_type"] == "Cancelación de Turno"
        assert "Ana Laura" in owner_kwargs["client_title"]

@pytest.mark.asyncio
async def test_meta_webhook_status_failure_handler():
    """Verify webhook handles Meta failure status payload gracefully."""
    from app.routers.webhook import receive_whatsapp_webhook
    from unittest.mock import MagicMock

    failure_payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "1592707075880588",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "5493435720312", "phone_number_id": "1306573512540922"},
                    "statuses": [{
                        "id": "wamid.TEST1234",
                        "status": "failed",
                        "recipient_id": "5493434536447",
                        "errors": [{
                            "code": 131047,
                            "title": "Re-engagement message",
                            "message": "Message failed to send because more than 24 hours have passed"
                        }]
                    }]
                },
                "field": "messages"
            }]
        }]
    }

    mock_db = MagicMock()
    mock_request = MagicMock()
    mock_request.json = AsyncMock(return_value=failure_payload)

    response = await receive_whatsapp_webhook(request=mock_request, db=mock_db)
    assert response["status"] == "success"
    assert "status or non-message event" in response["reason"]
