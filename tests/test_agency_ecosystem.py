import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_agency_home_loads_all_products():
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert "SOF-IA" in html
    assert "TECH &amp; AI STUDIO" in html or "TECH & AI STUDIO" in html
    assert "Sofía AI" in html
    assert "Súper Actualizador PRO" in html
    assert "Air Control" in html
    assert "/sofia" in html
    assert "/actualizador" in html
    assert "aircontrolpro.net" in html

def test_actualizador_landing_and_download():
    res = client.get("/actualizador")
    assert res.status_code == 200
    html = res.text
    assert "Actualizá 5.000 precios en 3 segundos" in html
    assert "Descargar Súper Actualizador PRO" in html

    dl = client.get("/descargar-actualizador", follow_redirects=False)
    assert dl.status_code == 307
    assert "drive.usercontent.google.com" in dl.headers["location"]

def test_air_control_redirect():
    res = client.get("/air-control", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "https://aircontrolpro.net/"

def test_sofia_routes_retrocompatibility():
    for path in ["/sofia", "/propuesta", "/precios"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "Sofia" in res.text or "Sofía" in res.text
