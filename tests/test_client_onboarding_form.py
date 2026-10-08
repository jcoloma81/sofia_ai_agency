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
    """Verify all public alias endpoints for the onboarding form return 200 and serve HTML with Meta policy and clear phone labels."""
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
        # Verify Meta Cloud policy notice and personal phone distinction are present
        assert "Requisito Oficial Obligatorio de Meta" in response.text
        assert "WhatsApp Personal del Titular" in response.text
        assert "Agenda Vigente" in response.text

def test_onboarding_submit_success_with_file_and_agenda(db):
    """
    Test submitting onboarding data with all fields, attached price list/agenda PDF file,
    and agenda status. Verifies Tenant and Prospect are created/updated and file is persisted.
    """
    # Clean previous tenant if any
    db.query(Tenant).filter(Tenant.slug.like("estetica_bella%")).delete()
    db.commit()

    file_content = b"%PDF-1.4 Mock PDF Content with Prices and Booked Slots"
    files = {
        "catalog_file": ("lista_precios_y_agenda.pdf", io.BytesIO(file_content), "application/pdf")
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
        "price_notes": "Limpieza facial $15.000, Masajes $20.000",
        "line_type": "shared",
        "agenda_status": "con_turnos_anotados"
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
    assert kb["line_type"] == "shared"
    assert kb["agenda_status"] == "con_turnos_anotados"
    assert kb["catalog_file_name"] == "lista_precios_y_agenda.pdf"
    assert kb["catalog_file_url"] is not None

    # Verify Prospect in DB
    prospect = db.query(Prospect).filter(Prospect.phone == tenant.owner_phone).first()
    assert prospect is not None
    assert prospect.name == "Estética Bella Paraná"
    assert prospect.status == "onboarded"

def test_onboarding_submit_dedicated_line_plan(db):
    """
    Test submitting onboarding requesting a dedicated line (Plan Enterprise Línea Propia).
    Verifies tenant is configured with plan_type='dedicated' and unlimited quota.
    """
    data = {
        "business_name": "Clínica Dental del Litoral",
        "business_type": "salud",
        "owner_name": "Dr. Fernando Ruiz",
        "owner_phone": "3434771122",
        "city": "Paraná",
        "operating_hours": "Lunes a Viernes 8 a 20 hs",
        "appointment_duration": "30 min",
        "line_type": "dedicated",
        "dedicated_phone": "3435009988",
        "agenda_status": "libre"
    }

    response = client.post("/api/onboarding/submit", data=data)
    assert response.status_code == 200, response.text
    res_data = response.json()
    assert res_data["status"] == "success"

    tenant = db.query(Tenant).filter(Tenant.slug == res_data["slug"]).first()
    assert tenant is not None
    assert tenant.plan_type == "dedicated"
    assert tenant.monthly_message_quota > 1000

    kb = json.loads(tenant.knowledge_base)
    assert kb["line_type"] == "dedicated"
    assert kb["dedicated_phone"] == "5493435009988"
    assert kb["agenda_status"] == "libre"

def test_onboarding_multi_tenant_database_isolation(db):
    """
    Verifies strict database isolation between two registered tenants.
    Even with similar names, each gets a unique slug and isolated knowledge base.
    """
    data1 = {
        "business_name": "Consultorio Dental San Martín",
        "business_type": "salud",
        "owner_name": "Dr. Álvarez",
        "owner_phone": "3434100001",
        "operating_hours": "Lunes a Viernes 8 a 12 hs"
    }
    data2 = {
        "business_name": "Consultorio Dental San Martín",
        "business_type": "salud",
        "owner_name": "Dra. Benítez",
        "owner_phone": "3434100002",
        "operating_hours": "Lunes a Viernes 16 a 20 hs"
    }

    res1 = client.post("/api/onboarding/submit", data=data1)
    res2 = client.post("/api/onboarding/submit", data=data2)

    slug1 = res1.json()["slug"]
    slug2 = res2.json()["slug"]

    # Slugs must be strictly unique and distinct
    assert slug1 != slug2
    assert slug1 == "consultorio_dental_san_martin"
    assert slug2 == "consultorio_dental_san_martin_1"

    t1 = db.query(Tenant).filter(Tenant.slug == slug1).first()
    t2 = db.query(Tenant).filter(Tenant.slug == slug2).first()

    assert t1.owner_phone != t2.owner_phone
    assert json.loads(t1.knowledge_base)["operating_hours"] != json.loads(t2.knowledge_base)["operating_hours"]

def test_onboarding_status_endpoint(db):
    """Test GET /api/onboarding/status/{slug}."""
    data = {
        "business_name": "Gym Fit Pro",
        "business_type": "gym",
        "owner_name": "Lucas Mendez",
        "owner_phone": "3434889900",
        "operating_hours": "Lunes a Sábado 7 a 22 hs"
    }
    submit_res = client.post("/api/onboarding/submit", data=data)
    slug = submit_res.json()["slug"]

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
