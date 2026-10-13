from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_preview_estilos_endpoint_and_themes():
    res = client.get("/estilos")
    assert res.status_code == 200
    html = res.text

    # 1. Alias endpoint check
    res_alias = client.get("/preview-estilos")
    assert res_alias.status_code == 200
    assert res_alias.text == html

    # 2. Themes & Selectors exist
    assert 'data-theme-target="entropy"' in html
    assert 'data-theme-target="swiss"' in html
    assert 'data-theme-target="gabinete"' in html
    assert 'data-theme-target="legacy"' in html

    # 3. New Spanish Methodology from Entropy Systems Benchmark
    assert "PROTOCOLO OPERATIVO: CLÍNICO V2" in html
    assert "SUPERVISIÓN EJECUTIVA: MODO DUEÑO" in html
    assert "Rescate Inteligente de Huecos" in html
    assert "Laboratorio de Calibración" in html
    assert "SETUP $30.000 / $45.000" in html

    # 4. Pricing and Commercial Models
    assert "$30.000" in html
    assert "$45.000" in html
    assert "Central Compartida" in html
    assert "Plan Enterprise" in html

    # 5. Fonts from Google Fonts included
    assert "Newsreader" in html
    assert "Space+Grotesk" in html
    assert "Cormorant+Garamond" in html
    assert "JetBrains+Mono" in html
