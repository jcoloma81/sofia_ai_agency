import pytest
import json
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from main import app
from app.models.prospect import Prospect
from app.services import brain, whatsapp

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_outreach_air_control_template(client, db):
    """Verifies outbound outreach uses approved prospeccion_aircontrol_v1 Meta template."""
    payload = {
        "phone": "5493434112233",
        "name": "Cabañas del Sol",
        "contact_name": "Horacio",
        "city": "Paraná",
        "campaign": "air_control"
    }
    with patch("app.services.whatsapp.send_whatsapp_template", new_callable=AsyncMock) as mock_tpl:
        mock_tpl.return_value = True
        resp = client.post("/api/v1/outreach/start-outreach", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "outreach_started"
        assert data["campaign"] == "air_control"
        
        # Verify prospeccion_aircontrol_v1 template was requested
        mock_tpl.assert_called_once()
        call_kwargs = mock_tpl.call_args[1]
        assert call_kwargs["template_name"] == "prospeccion_aircontrol_v1"
        assert call_kwargs["language_code"] == "es_AR"

    # Verify prospect record
    lead = db.query(Prospect).filter(Prospect.phone == "5493434112233").first()
    assert lead is not None
    assert lead.campaign == "air_control"
    assert lead.status == "contacted"
    assert "reducir hasta un 40% la factura de luz" in lead.conversation_history

def test_inbound_demo_request_parana(client, db):
    """When prospect responds 'DEMO' and is in Paraná, offers in-person visit and sends 2-min video."""
    lead = Prospect(
        phone="5493434998877",
        name="Cabañas Río Paraná",
        contact_name="Esteban",
        city="Paraná",
        campaign="air_control",
        status="contacted",
        conversation_history="[]"
    )
    db.add(lead)
    db.commit()

    meta_payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "5493434998877",
                        "id": "wamid.HBgLNTQ5MzQzNDk5ODg3NwUCABEYEkQ0...",
                        "type": "text",
                        "text": {"body": "DEMO"}
                    }],
                    "contacts": [{"profile": {"name": "Esteban"}}]
                }
            }]
        }]
    }

    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_video", new_callable=AsyncMock) as mock_vid, \
         patch("app.services.whatsapp.notify_owner_demo_requested", new_callable=AsyncMock) as mock_owner:
        
        mock_msg.return_value = True
        mock_vid.return_value = True

        resp = client.post("/webhook", json=meta_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["demo_requested"] is True
        assert "demo_air_control.mp4" in data["reply"]
        assert "visita presencial" in data["reply"]
        assert "Javier" in data["reply"]

    # Verify lead status
    db.refresh(lead)
    assert lead.status == "demo_requested"

def test_inbound_demo_request_colon(client, db):
    """When prospect responds 'DEMO' and is outside Paraná (e.g. Colón), offers 10-min video call."""
    lead = Prospect(
        phone="5493447112233",
        name="Complejo Termas Colón",
        contact_name="Marcela",
        city="Colón",
        campaign="air_control",
        status="contacted",
        conversation_history="[]"
    )
    db.add(lead)
    db.commit()

    meta_payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "5493447112233",
                        "id": "wamid.HBgLNTQ5MzQ0NzExMjIzMwUCABEYEkQ0...",
                        "type": "text",
                        "text": {"body": "quiero ver la demo por favor"}
                    }],
                    "contacts": [{"profile": {"name": "Marcela"}}]
                }
            }]
        }]
    }

    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.send_whatsapp_video", new_callable=AsyncMock) as mock_vid:
        mock_msg.return_value = True
        mock_vid.return_value = True

        resp = client.post("/webhook", json=meta_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["demo_requested"] is True
        assert "videollamada corta de 10 minutos" in data["reply"]

def test_meeting_confirmation_triggers_alert(client, db):
    """When prospect agrees on a day/time, sets meeting_scheduled and alerts Javier with Google Calendar link."""
    lead = Prospect(
        phone="5493434556677",
        name="Hotel Plaza Paraná",
        contact_name="Martín",
        city="Paraná",
        campaign="air_control",
        status="in_conversation",
        conversation_history="[]"
    )
    db.add(lead)
    db.commit()

    meta_payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "5493434556677",
                        "id": "wamid.HBgLNTQ5MzQzNDU1NjY3NwUCABEYEkQ1...",
                        "type": "text",
                        "text": {"body": "Dale Martín, el martes a las 10 hs me queda perfecto, pasate"}
                    }],
                    "contacts": [{"profile": {"name": "Martín"}}]
                }
            }]
        }]
    }

    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg, \
         patch("app.services.whatsapp.notify_javier_meeting_scheduled", new_callable=AsyncMock) as mock_alert, \
         patch("app.services.brain.generate_ai_response", new_callable=AsyncMock) as mock_ai:
        mock_msg.return_value = True
        mock_ai.return_value = ("¡Perfecto Martín! Ya te dejo agendada la reunión para el martes a las 10 hs.", True, "el martes a las 10 hs")

        resp = client.post("/webhook", json=meta_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["meeting_confirmed"] is True

    db.refresh(lead)
    assert lead.status == "meeting_scheduled"
    assert "martes a las 10" in lead.meeting_details.lower()

def test_human_takeover_silences_sofia(client, db):
    """When Javier activates human takeover, Sofia remains silent on subsequent prospect messages."""
    lead = Prospect(
        phone="5493434778899",
        name="Cabañas Victoria",
        city="Victoria",
        campaign="air_control",
        status="human_takeover",
        conversation_history="[]"
    )
    db.add(lead)
    db.commit()

    meta_payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "5493434778899",
                        "id": "wamid.HBgLNTQ5MzQzNDc3ODg5OQUCABEYEkQ2...",
                        "type": "text",
                        "text": {"body": "¿Hola estás ahí?"}
                    }]
                }
            }]
        }]
    }

    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg:
        resp = client.post("/webhook", json=meta_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"
        assert "human_takeover" in data["reason"]
        # Sofia did not send any message
        mock_msg.assert_not_called()

def test_opt_out_baja(client, db):
    """When prospect writes 'BAJA', marks as unsubscribed and sends polite farewell."""
    lead = Prospect(
        phone="5493434889900",
        name="Alojamiento Test",
        campaign="air_control",
        status="in_conversation",
        conversation_history="[]"
    )
    db.add(lead)
    db.commit()

    meta_payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "5493434889900",
                        "id": "wamid.HBgLNTQ5MzQzNDg4OTkwMAUCABEYEkQ3...",
                        "type": "text",
                        "text": {"body": "BAJA"}
                    }]
                }
            }]
        }]
    }

    with patch("app.services.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_msg:
        mock_msg.return_value = True
        resp = client.post("/webhook", json=meta_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "opt_out"

    db.refresh(lead)
    assert lead.status == "unsubscribed"
