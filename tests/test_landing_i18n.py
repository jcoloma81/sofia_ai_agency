from fastapi.testclient import TestClient
from main import app
import re

client = TestClient(app)

def test_landing_page_multilingual_and_responsive():
    # 1. Landing serves 200 OK
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    # 2. Viewport meta tag present for responsive design
    assert 'meta name="viewport"' in html
    assert 'viewport-fit=cover' in html

    # 3. Language switcher elements exist
    assert 'class="lang-switcher"' in html
    assert 'data-lang="es"' in html
    assert 'data-lang="pt"' in html
    assert 'data-lang="en"' in html

    # 4. Multilingual switcher function exists
    assert "function setLanguage(lang)" in html
    assert "localStorage.setItem('sofia_lang', lang)" in html

    # 5. Core sections have data-i18n markers
    assert 'data-i18n="hero_badge"' in html
    assert 'data-i18n-html="hero_title"' in html
    assert 'data-i18n="metric_latency_lbl"' in html
    assert 'data-i18n="problem_title"' in html
    assert 'data-i18n="solution_title"' in html
    assert 'data-i18n="pillars_title"' in html

    # 6. WhatsApp buttons have dynamic message routing
    assert 'class="btn-primary btn-whatsapp"' in html
    assert 'wa.me/5493435720312' in html

def test_propuesta_and_precios_aliases():
    res_propuesta = client.get("/propuesta")
    assert res_propuesta.status_code == 200
    assert "Sofia AI" in res_propuesta.text

    res_precios = client.get("/precios")
    assert res_precios.status_code == 200
    assert "Sofia AI" in res_precios.text
