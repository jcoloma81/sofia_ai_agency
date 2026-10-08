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
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
  * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
  }
  body {
    width: 1640px;
    height: 924px;
    background-color: #070B14;
    background-image: 
      radial-gradient(circle at 18% 25%, rgba(16, 185, 129, 0.16) 0%, transparent 45%),
      radial-gradient(circle at 82% 70%, rgba(59, 130, 246, 0.14) 0%, transparent 45%),
      radial-gradient(circle at 50% 50%, rgba(139, 92, 246, 0.08) 0%, transparent 60%);
    color: #F8FAFC;
    overflow: hidden;
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 44px 70px 38px 70px;
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
    background: rgba(16, 185, 129, 0.12);
    border: 1.5px solid rgba(16, 185, 129, 0.45);
    color: #10B981;
    padding: 8px 24px;
    border-radius: 9999px;
    font-size: 13.5px;
    font-weight: 800;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    margin-bottom: 14px;
    box-shadow: 0 0 20px rgba(16, 185, 129, 0.2);
  }

  .main-title {
    font-size: 47px;
    font-weight: 900;
    line-height: 1.15;
    letter-spacing: -1.2px;
    margin-bottom: 10px;
    max-width: 1360px;
  }

  .main-title .gradient-text {
    background: linear-gradient(135deg, #10B981 0%, #38BDF8 50%, #818CF8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }

  .subtitle {
    font-size: 20px;
    color: #94A3B8;
    font-weight: 500;
    line-height: 1.4;
    max-width: 1100px;
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
    background: rgba(15, 23, 42, 0.75);
    border: 1.5px solid rgba(51, 65, 85, 0.7);
    border-radius: 20px;
    padding: 22px 26px;
    display: flex;
    align-items: flex-start;
    gap: 20px;
    backdrop-filter: blur(12px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    transition: all 0.2s;
  }

  .feature-card.highlight {
    border-color: rgba(16, 185, 129, 0.5);
    background: rgba(15, 23, 42, 0.88);
  }

  .icon-wrapper {
    width: 58px;
    height: 58px;
    border-radius: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 28px;
    flex-shrink: 0;
  }

  .icon-green {
    background: rgba(16, 185, 129, 0.15);
    border: 1.5px solid rgba(16, 185, 129, 0.4);
    box-shadow: 0 0 16px rgba(16, 185, 129, 0.25);
  }

  .icon-blue {
    background: rgba(56, 189, 248, 0.15);
    border: 1.5px solid rgba(56, 189, 248, 0.4);
    box-shadow: 0 0 16px rgba(56, 189, 248, 0.25);
  }

  .icon-purple {
    background: rgba(168, 85, 247, 0.15);
    border: 1.5px solid rgba(168, 85, 247, 0.4);
    box-shadow: 0 0 16px rgba(168, 85, 247, 0.25);
  }

  .icon-amber {
    background: rgba(245, 158, 11, 0.15);
    border: 1.5px solid rgba(245, 158, 11, 0.4);
    box-shadow: 0 0 16px rgba(245, 158, 11, 0.25);
  }

  .card-content {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .card-title {
    font-size: 20px;
    font-weight: 800;
    color: #FFFFFF;
    letter-spacing: -0.3px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .card-title .tag-pill {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    padding: 3px 8px;
    border-radius: 6px;
    background: rgba(16, 185, 129, 0.2);
    color: #34D399;
  }

  .card-desc {
    font-size: 15px;
    color: #CBD5E1;
    line-height: 1.42;
    font-weight: 500;
  }

  /* Bottom Bar */
  .footer-zone {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 16px;
    border-top: 1px solid rgba(51, 65, 85, 0.45);
    width: 100%;
  }

  .footer-left {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .footer-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #10B981;
    box-shadow: 0 0 12px #10B981;
  }

  .footer-text {
    font-size: 15px;
    color: #94A3B8;
    font-weight: 600;
  }

  .footer-text strong {
    color: #F1F5F9;
  }

  .footer-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: #10B981;
  }
</style>
</head>
<body>

  <div class="header-zone">
    <div class="badge-pill">
      <span>⚡</span> TECNOLOGÍA AUTÓNOMA CON IA • EN TU WHATSAPP 24/7
    </div>
    <h1 class="main-title">
      Olvidate de los chatbots tradicionales.<br>
      <span class="gradient-text">Tu negocio necesita una empleada con IA que resuelva todo.</span>
    </h1>
    <p class="subtitle">
      El sistema que vive dentro de WhatsApp: comprende notas de voz, opera tu agenda y recupera cancelaciones en tiempo real.
    </p>
  </div>

  <div class="cards-grid">
    <!-- Card 1 -->
    <div class="feature-card highlight">
      <div class="icon-wrapper icon-green">🎙️</div>
      <div class="card-content">
        <div class="card-title">
          COMPRENDE NOTAS DE VOZ
          <span class="tag-pill">IA Multimodal</span>
        </div>
        <p class="card-desc">
          Tus clientes le mandan audios desordenados como a una recepcionista real, y Sofía entiende pedidos, fechas y consultas al instante.
        </p>
      </div>
    </div>

    <!-- Card 2 -->
    <div class="feature-card highlight">
      <div class="icon-wrapper icon-blue">🔄</div>
      <div class="card-content">
        <div class="card-title">
          RELLENA TURNOS CAÍDOS SOLA
          <span class="tag-pill" style="background: rgba(56, 189, 248, 0.2); color: #38BDF8;">Cero Ausentismo</span>
        </div>
        <p class="card-desc">
          Si alguien cancela, detecta el hueco libre y contacta de inmediato a la lista de espera para reocupar el turno. No perdés facturación.
        </p>
      </div>
    </div>

    <!-- Card 3 -->
    <div class="feature-card">
      <div class="icon-wrapper icon-purple">📱</div>
      <div class="card-content">
        <div class="card-title">
          UN CONTACTO DIRECTO EN WHATSAPP
          <span class="tag-pill" style="background: rgba(168, 85, 247, 0.2); color: #C084FC;">Cero Apps</span>
        </div>
        <p class="card-desc">
          Sin descargar aplicaciones, sin registros ni webs lentas. Tus clientes le escriben directo al número que ya usan todos los días.
        </p>
      </div>
    </div>

    <!-- Card 4 -->
    <div class="feature-card">
      <div class="icon-wrapper icon-amber">👑</div>
      <div class="card-content">
        <div class="card-title">
          MODO DUEÑO POR VOZ
          <span class="tag-pill" style="background: rgba(245, 158, 11, 0.2); color: #FBBF24;">Control Total</span>
        </div>
        <p class="card-desc">
          Le hablás por audio desde tu WhatsApp personal para ver turnos del día, reportes de ventas o darle directivas, sin tocar la PC.
        </p>
      </div>
    </div>
  </div>

  <div class="footer-zone">
    <div class="footer-left">
      <div class="footer-dot"></div>
      <span class="footer-text">Puesta en marcha ágil en pocos días hábiles • 100% en la nube • Cero contratos de permanencia</span>
    </div>
    <div class="footer-brand">
      <span>⚡</span> SOFÍA AI AGENCY
    </div>
  </div>

</body>
</html>
"""

def generate_cover():
    print(f"🎨 Generando nueva portada de Facebook (1640x924 px)...")
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
    print(f"✅ Portada generada con éxito: {OUTPUT_PATH} ({size_kb:.1f} KB, 1640x924 px)")

if __name__ == "__main__":
    generate_cover()
