from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_landing_page_pricing_and_rubros_sections():
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    # 1. Rubros Section
    assert 'id="rubros"' in html
    assert "Salud, Consultorios" in html
    assert "Gimnasios, Clubes" in html
    assert "Veterinarias" in html
    assert "Ópticas &amp; Talleres" in html or "Ópticas & Talleres" in html

    # 2. Pricing Section ($30.000 ARS Policy)
    assert 'id="precios"' in html
    assert "$30.000" in html
    assert "Plan Central Compartida" in html
    assert "Plan Enterprise" in html
    assert "150 Mensajes Salientes" in html
    assert "$80.000" in html
    assert "Pack de 100 Mensajes Extra por solo $4.500 ARS" in html

    # 3. Downloads Section
    assert 'id="descargas"' in html
    assert "/descargar-guia-pdf" in html
    assert "/descargar-modo-jefe-pdf" in html
    assert "/descargar-catalogo-pdf" in html
    assert "/hoja-de-ruta" in html

def test_download_and_doc_endpoints():
    res_guia_pdf = client.get("/descargar-guia-pdf")
    assert res_guia_pdf.status_code == 200
    assert res_guia_pdf.headers["content-type"] == "application/pdf"

    res_modo_jefe_pdf = client.get("/descargar-modo-jefe-pdf")
    assert res_modo_jefe_pdf.status_code == 200
    assert res_modo_jefe_pdf.headers["content-type"] == "application/pdf"

    res_costos_pdf = client.get("/descargar-costos-pdf")
    assert res_costos_pdf.status_code == 200
    assert res_costos_pdf.headers["content-type"] == "application/pdf"

    res_costos_html = client.get("/modelo-costos")
    assert res_costos_html.status_code == 200
    assert "Política de Precios & Costos Meta" in res_costos_html.text

    res_catalogo_pdf = client.get("/descargar-catalogo-pdf")
    assert res_catalogo_pdf.status_code == 200
    assert res_catalogo_pdf.headers["content-type"] == "application/pdf"

    res_catalogo_html = client.get("/catalogo-plantillas")
    assert res_catalogo_html.status_code == 200
    assert "Catálogo Visual de Plantillas" in res_catalogo_html.text
