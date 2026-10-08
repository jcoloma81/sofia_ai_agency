import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from app.services import whatsapp
from app.config.settings import settings


def test_meta_master_templates_json_integrity():
    """Verify that all 6 official master templates are properly formatted in meta_master_templates.json."""
    templates_path = Path(__file__).resolve().parent.parent / "app" / "data" / "meta_master_templates.json"
    assert templates_path.exists(), "meta_master_templates.json must exist"

    with open(templates_path, "r", encoding="utf-8") as f:
        templates = json.load(f)

    assert len(templates) == 6, f"Expected 6 master templates, found {len(templates)}"

    expected_names = {
        "recordatorio_turno_v2": "UTILITY",
        "adelanta_turno_v1": "UTILITY",
        "pedido_listo_retiro_v1": "UTILITY",
        "aviso_vencimiento_cuota_v1": "UTILITY",
        "aviso_control_preventivo_v1": "UTILITY",
        "campana_promo_v1": "MARKETING",
    }

    found_names = {}
    for tpl in templates:
        name = tpl.get("name")
        cat = tpl.get("category")
        lang = tpl.get("language")
        components = tpl.get("components", [])

        assert name in expected_names, f"Unexpected template name: {name}"
        assert cat == expected_names[name], f"Template {name} category mismatch: expected {expected_names[name]}, got {cat}"
        assert lang == "es_AR", f"Language for {name} should be es_AR"

        comp_types = [c.get("type") for c in components]
        assert "BODY" in comp_types, f"Template {name} must have a BODY component"
        assert "BUTTONS" in comp_types, f"Template {name} must have a BUTTONS component"

        found_names[name] = cat

    assert found_names == expected_names


@pytest.mark.asyncio
async def test_send_whatsapp_template_with_body_params(monkeypatch):
    """Verify send_whatsapp_template wraps body_params into Meta-compliant components."""
    posted_payload = {}

    async def fake_post(url, json=None, headers=None):
        nonlocal posted_payload
        posted_payload = json
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"messages":[{"id":"wamid.test"}]}'
        mock_resp.json.return_value = {"messages": [{"id": "wamid.test"}]}
        return mock_resp

    # Undo conftest mock for this specific test to test the internal logic
    monkeypatch.undo()

    monkeypatch.setattr(settings, "META_ACCESS_TOKEN", "fake_token")
    monkeypatch.setattr(settings, "META_PHONE_NUMBER_ID", "fake_phone_id")

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=fake_post)

    with patch("httpx.AsyncClient", return_value=mock_client):
        success = await whatsapp.send_whatsapp_template(
            to_phone="+54 9 343 555-1234",
            template_name="recordatorio_turno_v2",
            language_code="es_AR",
            body_params=["Martín", "Clínica Dental Sonrisas", "Mañana Martes", "16:30", "Limpieza", "Av. Corrientes 1234"]
        )

        assert success is True
        assert posted_payload["template"]["name"] == "recordatorio_turno_v2"
        assert posted_payload["template"]["language"]["code"] == "es_AR"
        
        components = posted_payload["template"]["components"]
        assert len(components) == 1
        assert components[0]["type"] == "body"
        params = components[0]["parameters"]
        assert len(params) == 6
        assert params[0]["text"] == "Martín"
        assert params[1]["text"] == "Clínica Dental Sonrisas"
        assert params[5]["text"] == "Av. Corrientes 1234"
