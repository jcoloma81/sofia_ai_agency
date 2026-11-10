import pytest
from fastapi.testclient import TestClient
from main import app
from app.models.tenant import Tenant

client = TestClient(app)

def test_clinic_access_card_endpoint(db):
    """Verifies that /acceso/{slug} and /qr/{slug} return the printable HTML poster with QR."""
    # Ensure tenant exists
    t = db.query(Tenant).filter(Tenant.slug == "clinica_test_qr").first()
    if not t:
        t = Tenant(
            slug="clinica_test_qr",
            name="Consultorios San Lucas",
            business_type="salud",
            owner_phone="5493434112233",
            owner_name="Dr. Lucas Vega",
            deep_link_keyword="San_Lucas",
            active=True
        )
        db.add(t)
        db.commit()

    # Test /acceso/clinica_test_qr
    res = client.get("/acceso/clinica_test_qr")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Consultorios San Lucas" in res.text
    assert "Dr. Lucas Vega" in res.text
    assert "api.qrserver.com" in res.text
    assert "Imprimir Cartel" in res.text
    assert "Copiar Link" in res.text

    # Test /qr/clinica_test_qr alias
    res_qr = client.get("/qr/clinica_test_qr")
    assert res_qr.status_code == 200
    assert "Consultorios San Lucas" in res_qr.text

def test_clinic_access_card_404_for_unknown_slug():
    """Returns 404 for non-existent clinic slug."""
    res = client.get("/acceso/slug_inexistente_12345")
    assert res.status_code == 404
