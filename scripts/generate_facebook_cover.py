import os
import subprocess
from PIL import Image

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "sofia_facebook_cover.png")
HTML_TEMP_PATH = "/tmp/sofia_facebook_cover_temp.html"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Sofía AI — Portada de Facebook</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,500;0,6..72,600;0,6..72,700;1,6..72,400;1,6..72,600&family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }
  body {
    width: 1640px;
    height: 924px;
    background-color: #0B0D10;
    background-image: 
      radial-gradient(circle at 15% 20%, rgba(5, 150, 105, 0.07) 0%, transparent 45%),
      radial-gradient(circle at 85% 75%, rgba(15, 23, 42, 0.5) 0%, transparent 50%);
    color: #F4F3EE;
    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
    overflow: hidden;
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 44px 70px 38px 70px;
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  /* Header Section */
  .header-zone {
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .badge-pill {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: #D1D5DB;
    padding: 7px 22px;
    border-radius: 9999px;
    font-size: 12.5px;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    margin-bottom: 14px;
  }

  .badge-pill .pulse-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #059669;
  }

  .main-title {
    font-family: 'Newsreader', Georgia, serif;
    font-size: 48px;
    font-weight: 600;
    line-height: 1.15;
    letter-spacing: -0.8px;
    margin-bottom: 12px;
    max-width: 1380px;
    color: #F4F3EE;
  }

  .main-title span {
    font-family: 'Newsreader', Georgia, serif;
    font-style: italic;
    font-weight: 400;
    color: #059669;
  }

  .subtitle {
    font-size: 19px;
    color: #9FA6B2;
    font-weight: 400;
    line-height: 1.45;
    max-width: 1120px;
    margin-bottom: 24px;
  }

  /* 4 Pillars Grid (2x2) */
  .cards-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px 24px;
    width: 100%;
    max-width: 1500px;
    margin: 0 auto;
  }

  .feature-card {
    background: #13161C;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 16px;
    padding: 22px 26px;
    display: flex;
    align-items: flex-start;
    gap: 20px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  }

  .feature-card.highlight {
    border-color: rgba(5, 150, 105, 0.4);
    background: #151922;
  }

  .icon-wrapper {
    width: 50px;
    height: 50px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'JetBrains Mono', monospace;
    font-size: 15px;
    font-weight: 700;
    flex-shrink: 0;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: #9FA6B2;
  }

  .feature-card.highlight .icon-wrapper {
    color: #6EE7B7;
    border-color: rgba(5, 150, 105, 0.3);
    background: rgba(5, 150, 105, 0.1);
  }

  .card-content {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .card-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 18.5px;
    font-weight: 700;
    color: #F4F3EE;
    letter-spacing: -0.3px;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .card-title .tag-pill {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    padding: 3px 8px;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #9FA6B2;
  }

  .feature-card.highlight .card-title .tag-pill {
    background: rgba(5, 150, 105, 0.12);
    border-color: rgba(5, 150, 105, 0.3);
    color: #6EE7B7;
  }

  .card-desc {
    font-size: 14.5px;
    color: #9FA6B2;
    line-height: 1.45;
    font-weight: 400;
  }

  /* Bottom Bar */
  .footer-zone {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 16px;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    width: 100%;
  }

  .footer-left {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .footer-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #059669;
  }

  .footer-text {
    font-size: 13.5px;
    color: #9FA6B2;
    font-weight: 500;
  }

  .footer-text strong {
    color: #F4F3EE;
  }

  .footer-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1px;
    color: #F4F3EE;
  }

  .footer-brand .brand-badge {
    width: 24px;
    height: 24px;
    border-radius: 6px;
    background: #13161C;
    border: 1px solid rgba(255, 255, 255, 0.15);
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Newsreader', serif;
    font-size: 13px;
    color: #F4F3EE;
  }
</style>
</head>
<body>

  <div class="header-zone">
    <div class="badge-pill">
      <span class="pulse-dot"></span> PROTOCOLO DE OPERACIÓN CLÍNICA • INFRAESTRUCTURA AGÉNTICA
    </div>
    <h1 class="main-title">
      Sustitución de Chatbots Rígidos: <span>Infraestructura Agéntica 24/7 en WhatsApp</span>
    </h1>
    <p class="subtitle">
      Comprensión de lenguaje natural rioplatense (texto y audios), rescate autónomo de turnos caídos en 90 segundos y supervisión ejecutiva directa en tu celular.
    </p>
  </div>

  <div class="cards-grid">
    <!-- Card 1 -->
    <div class="feature-card highlight">
      <div class="icon-wrapper">01</div>
      <div class="card-content">
        <div class="card-title">
          RESCATE AUTÓNOMO DE HUECOS
          <span class="tag-pill">Protocolo Clínico</span>
        </div>
        <p class="card-desc">
          Ante una cancelación, contacta al instante a los pacientes en lista de espera y reasigna el turno en menos de 90 segundos, protegiendo tu facturación.
        </p>
      </div>
    </div>

    <!-- Card 2 -->
    <div class="feature-card">
      <div class="icon-wrapper">02</div>
      <div class="card-content">
        <div class="card-title">
          COMPRENSIÓN MULTIMODAL NATIVA
          <span class="tag-pill">Audio &amp; Texto</span>
        </div>
        <p class="card-desc">
          Tus pacientes envían notas de voz espontáneas como a una secretaria real. Sofía interpreta el motivo de consulta, disponibilidad y responde con calidez.
        </p>
      </div>
    </div>

    <!-- Card 3 -->
    <div class="feature-card">
      <div class="icon-wrapper">03</div>
      <div class="card-content">
        <div class="card-title">
          SUPERVISIÓN EJECUTIVA (MODO DUEÑO)
          <span class="tag-pill">Control Directo</span>
        </div>
        <p class="card-desc">
          Alertas médicas ejecutivas y directivas por audio directamente en tu WhatsApp personal. Modificá aranceles o pausá la atención sin tocar la computadora.
        </p>
      </div>
    </div>

    <!-- Card 4 -->
    <div class="feature-card">
      <div class="icon-wrapper">04</div>
      <div class="card-content">
        <div class="card-title">
          BASE DE CONOCIMIENTO IN-CONTEXT
          <span class="tag-pill">Cero Alucinación</span>
        </div>
        <p class="card-desc">
          Obras sociales, aranceles y requisitos clínicos inyectados directamente en el contexto de Gemini. Cero bases vectoriales frágiles y 100% de precisión.
        </p>
      </div>
    </div>
  </div>

  <div class="footer-zone">
    <div class="footer-left">
      <div class="footer-dot"></div>
      <span class="footer-text"><strong>Laboratorio de Calibración a Medida</strong> • Meta Cloud API Oficial Verificada • Aislamiento Multi-Tenant</span>
    </div>
    <div class="footer-brand">
      <div class="brand-badge">S</div> SOFÍA AI SYSTEMS
    </div>
  </div>

</body>
</html>
"""

def generate_cover():
    print("🎨 Generando portada sobria estilo Entropy Editorial (1640x924 px)...")
    with open(HTML_TEMP_PATH, "w", encoding="utf-8") as f:
        f.write(HTML_TEMPLATE)

    raw_png = "/tmp/sofia_cover_raw.png"
    cmd = [
        "google-chrome",
        "--headless=new",
        "--disable-gpu",
        "--window-size=1640,1020",
        f"--screenshot={raw_png}",
        HTML_TEMP_PATH
    ]
    subprocess.run(cmd, check=True)

    im = Image.open(raw_png)
    # Recorte exacto a 1640x924
    im_cropped = im.crop((0, 0, 1640, 924))
    im_cropped.save(OUTPUT_PATH, optimize=True)
    
    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"✅ Portada sobria generada con éxito: {OUTPUT_PATH} ({size_kb:.1f} KB, 1640x924 px)")

if __name__ == "__main__":
    generate_cover()
