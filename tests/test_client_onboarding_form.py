import io
import os
import json
import pytest
from fastapi.testclient import TestClient

from main import app
from app.models.tenant import Tenant
from app.models.prospect import Prospect
from app.database import get_db

client = TestClient(app)

def test_onboarding_page_routes_serve_html():
    """Verify all public alias endpoints for the onboarding form return 200 and serve HTML."""
    aliases = [
        "/alta",
        "/alta-cliente",
        "/onboarding",
        "/ficha",
        "/ficha_alta_cliente.html"
    ]
    for route in aliases:
        response = client.get(route)
        assert response.status_code == 200, f"Route {route} failed with {response.status_code}"
        assert "text/html" in response.headers.get("content-type", "")
        assert "Puesta en Marcha Digital" in response.text
        assert "sofia.ia.agency" in response.text
        assert "30.000" in response.text

def test_onboarding_submit_success_with_file(db):
    """
    Test submitting onboarding data with all fields and an attached price list PDF file.
    Verifies Tenant and Prospect are created/updated and file is persisted.
    """
    # Clean previous tenant if any
    db.query(Tenant).filter(Tenant.slug.like("estetica_bella%")).delete()
    db.commit()

    file_content = b"%PDF-1.4 Mock PDF Content with Prices"
    files = {
        "catalog_file": ("lista_precios_2026.pdf", io.BytesIO(file_content), "application/pdf")
    }
    data = {
        "business_name": "Estética Bella Paraná",
        "business_type": "salud",
        "owner_name": "Lic. Florencia Gómez",
        "owner_phone": "3434112233",
        "city": "Paraná, Entre Ríos",
        "operating_hours": "Lunes a Viernes de 9:00 a 19:00 hs",
        "appointment_duration": "45 min",
        "requires_deposit": "si",
        "deposit_amount": "5000",
        "emergency_contact": "3434998877",
        "price_notes": "Limpieza facial $15.000, Masajes $20.000"
    }

    response = client.post("/api/onboarding/submit", data=data, files=files)
    assert response.status_code == 200, response.text
    res_data = response.json()
    assert res_data["status"] == "success"
    assert "estetica_bella" in res_data["slug"]
    assert res_data["file_uploaded"] is True
    assert res_data["plan_amount"] == 30000

    # Verify Tenant in DB
    tenant = db.query(Tenant).filter(Tenant.slug == res_data["slug"]).first()
    assert tenant is not None
    assert tenant.name == "Estética Bella Paraná"
    assert tenant.business_type == "salud"
    assert tenant.owner_phone.startswith("5493434112233")
    assert tenant.plan_type == "shared"
    assert tenant.monthly_message_quota == 150
    assert tenant.active is True

    # Verify Knowledge Base JSON contains parsed parameters
    kb = json.loads(tenant.knowledge_base)
    assert kb["owner_name"] == "Lic. Florencia Gómez"
    assert kb["requires_deposit"] is True
    assert kb["deposit_amount"] == "5000"
    assert kb["appointment_duration"] == "45 min"
    assert kb["catalog_file_name"] == "lista_precios_2026.pdf"
    assert kb["catalog_file_url"] is not None

    # Verify Prospect in DB
    prospect = db.query(Prospect).filter(Prospect.phone == tenant.owner_phone).first()
    assert prospect is not None
    assert prospect.name == "Estética Bella Paraná"
    assert prospect.status == "onboarded"

def test_onboarding_submit_success_text_only(db):
    """
    Test submitting onboarding data without file (only text notes for prices).
    """
    data = {
        "business_name": "Taller Mecánico El Rayo",
        "business_type": "taller",
        "owner_name": "Carlos Rossi",
        "owner_phone": "3434556677",
        "city": "Paraná",
        "operating_hours": "Lunes a Viernes 8 a 17 hs",
        "appointment_duration": "60 min",
        "requires_deposit": "no",
        "price_notes": "Alineación y balanceo $25.000. Cambio de aceite y filtros $45.000."
    }

    response = client.post("/api/onboarding/submit", data=data)
    assert response.status_code == 200, response.text
    res_data = response.json()
    assert res_data["status"] == "success"
    assert "taller_mecanico_el_rayo" in res_data["slug"]
    assert res_data["file_uploaded"] is False

    # Check Tenant in DB
    tenant = db.query(Tenant).filter(Tenant.slug == res_data["slug"]).first()
    assert tenant is not None
    assert tenant.name == "Taller Mecánico El Rayo"
    assert tenant.business_type == "taller"

def test_onboarding_status_endpoint(db):
    """Test GET /api/onboarding/status/{slug}."""
    # First create a tenant
    data = {
        "business_name": "Gym Fit Pro",
        "business_type": "gym",
        "owner_name": "Lucas Mendez",
        "owner_phone": "3434889900",
        "operating_hours": "Lunes a Sábado 7 a 22 hs"
    }
    submit_res = client.post("/api/onboarding/submit", data=data)
    slug = submit_res.json()["slug"]

    # Now query status
    status_res = client.get(f"/api/onboarding/status/{slug}")
    assert status_res.status_code == 200
    s_data = status_res.json()
    assert s_data["status"] == "success"
    assert s_data["name"] == "Gym Fit Pro"
    assert s_data["business_type"] == "gym"
    assert s_data["active"] is True

def test_onboarding_status_not_found():
    response = client.get("/api/onboarding/status/non_existent_slug_99999")
    assert response.status_code == 404
