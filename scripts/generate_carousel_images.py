import os
import subprocess

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "carrusel_meta_ads")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SLIDES = [
    {
        "filename": "slide_1_portada.png",
        "badge": "⚡ SOFÍA AI • ASISTENTE PARA WHATSAPP",
        "title": "¿Cuánta plata pierde tu negocio por no responder WhatsApp a tiempo?",
        "subtitle": "El costo invisible de no tener un asistente las 24 horas en tu equipo.",
        "content_html": """
        <div class="hero-box">
          <div class="wa-icon-glow">💬</div>
          <div class="stats-pills">
            <div class="pill">❌ Pacientes que faltan</div>
            <div class="pill">❌ Socios que se van</div>
            <div class="pill">❌ Cuotas sin cobrar del 1 al 10</div>
            <div class="pill">❌ Consultas que nadie responde</div>
          </div>
        </div>
        """,
        "footer": "Deslizá para ver cómo lo solucionamos en tu rubro 👉"
    },
    {
        "filename": "slide_2_consultorios.png",
        "badge": "🏥 SALUD & CONSULTORIOS",
        "title": "CONSULTORIOS Y CLÍNICAS",
        "subtitle": "¿El paciente no vino? Sofía reprograma y rellena el turno sola.",
        "content_html": """
        <div class="cards-stack">
          <div class="card problem">
            <div class="card-tag">❌ El problema diario</div>
            <p>Pacientes que faltan sin avisar, consultas vacías que no cobrás y tu secretaria colapsada de mensajes a toda hora.</p>
          </div>
          <div class="card solution">
            <div class="card-tag">✅ Con Sofía AI (En Automático)</div>
            <p>• Doble recordatorio anti-ausentismo.<br>• <strong>Reprogramación autónoma:</strong> si alguien cancela, ofrece el turno de inmediato a otro paciente en espera.</p>
          </div>
        </div>
        """,
        "footer": "Tu secretaria atiende en paz. Vos no perdés consultas."
    },
    {
        "filename": "slide_3_gimnasios.png",
        "badge": "💪 GIMNASIOS & FITNESS",
        "title": "GIMNASIOS Y CENTROS DEPORTIVOS",
        "subtitle": "Reactivá socios dormidos y cuotas que dabas por perdidas.",
        "content_html": """
        <div class="cards-stack">
          <div class="card problem">
            <div class="card-tag">❌ El problema diario</div>
            <p>Decenas de alumnos dejan de ir en silencio. Nadie tiene tiempo de escribirles uno por uno para invitarlos a volver.</p>
          </div>
          <div class="card solution">
            <div class="card-tag">✅ Con Sofía AI (En Automático)</div>
            <p>• <strong>Campañas de Reactivación:</strong> detecta socios inactivos (+60 días) y les escribe con mensajes cálidos.<br>• <strong>Cobro de Cuotas (1 al 10):</strong> recordatorio automático con link de pago.<br>• Informa precios y anota pases 24/7.</p>
          </div>
        </div>
        """,
        "footer": "Recuperá ingresos todos los meses sin mover un dedo."
    },
    {
        "filename": "slide_4_veterinarias.png",
        "badge": "🐾 VETERINARIAS & PET SHOPS",
        "title": "VETERINARIAS Y PET SHOPS",
        "subtitle": "El 60% de los dueños se olvidan de las vacunas si no les avisás.",
        "content_html": """
        <div class="cards-stack">
          <div class="card problem">
            <div class="card-tag">❌ El problema diario</div>
            <p>La rutina tapa a los dueños, se pasan los plazos de vacunación o desparasitación y perdés tratamientos periódicos.</p>
          </div>
          <div class="card solution">
            <div class="card-tag">✅ Con Sofía AI (En Automático)</div>
            <p>• <strong>Recordatorios de Vacunación:</strong> avisa por WhatsApp antes del vencimiento.<br>• Coordina turnos de clínica y peluquería en segundos sin frenar tu quirófano.</p>
          </div>
        </div>
        """,
        "footer": "Fidelizá a tus clientes y mantené la agenda completa."
    },
    {
        "filename": "slide_5_cierre_cta.png",
        "badge": "🚀 TU NEGOCIO EN AUTOMÁTICO",
        "title": "TODO EN AUTOMÁTICO.",
        "subtitle": "Un abono accesible que se paga solo con 1 turno salvado.",
        "content_html": """
        <div class="pricing-box">
          <div class="price-big">$30.000 <span class="price-period">ARS / mes</span></div>
          <ul class="benefits-list">
            <li>✓ Sin contratos atados a largo plazo</li>
            <li>✓ Atiende texto y <strong>audios de voz</strong> 24/7</li>
            <li>✓ Puesta en marcha ágil en pocos días hábiles</li>
            <li>✓ Alertas en vivo a tu celular</li>
          </ul>
        </div>
        <div class="cta-banner">
          🟢 TOCÁ EL BOTÓN DE ABAJO Y PROBALA EN VIVO 👇
        </div>
        """,
        "footer": "Mandale un mensaje o audio a Sofía ahora mismo."
    }
]

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    width: 1080px;
    height: 1080px;
    background: #0B0F19;
    color: #F9FAFB;
    font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 70px 65px;
    position: relative;
    overflow: hidden;
  }
  /* Background glow effects */
  body::before {
    content: '';
    position: absolute;
    top: -150px;
    right: -150px;
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, rgba(16, 185, 129, 0.18) 0%, transparent 70%);
    z-index: 0;
  }
  body::after {
    content: '';
    position: absolute;
    bottom: -150px;
    left: -150px;
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, rgba(59, 130, 246, 0.15) 0%, transparent 70%);
    z-index: 0;
  }
  .header-zone, .main-zone, .footer-zone {
    position: relative;
    z-index: 1;
  }
  .badge {
    display: inline-flex;
    align-items: center;
    background: rgba(16, 185, 129, 0.12);
    border: 1px solid rgba(16, 185, 129, 0.35);
    color: #10B981;
    font-size: 20px;
    font-weight: 800;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    padding: 10px 22px;
    border-radius: 50px;
    margin-bottom: 24px;
  }
  .title {
    font-size: 46px;
    font-weight: 800;
    line-height: 1.18;
    color: #FFFFFF;
    letter-spacing: -1px;
    margin-bottom: 16px;
    max-width: 950px;
  }
  .subtitle {
    font-size: 24px;
    color: #9CA3AF;
    line-height: 1.45;
    font-weight: 500;
    max-width: 900px;
  }
  .hero-box {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    margin: 30px 0;
  }
  .wa-icon-glow {
    font-size: 130px;
    filter: drop-shadow(0 0 45px rgba(37, 211, 102, 0.45));
    margin-bottom: 20px;
  }
  .stats-pills {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
    width: 100%;
    max-width: 900px;
    margin: 0 auto;
  }
  .pill {
    background: #111827;
    border: 1px solid #1F2937;
    padding: 16px 20px;
    border-radius: 14px;
    font-size: 21px;
    font-weight: 700;
    color: #F87171;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
  }
  .cards-stack {
    display: flex;
    flex-direction: column;
    gap: 20px;
    margin: 25px 0;
  }
  .card {
    background: #111827;
    border: 1px solid #1F2937;
    border-radius: 20px;
    padding: 26px 32px;
  }
  .card.problem {
    border-left: 6px solid #EF4444;
  }
  .card.solution {
    border-left: 6px solid #10B981;
    background: linear-gradient(180deg, #13242B 0%, #111827 100%);
  }
  .card-tag {
    font-size: 18px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 10px;
  }
  .card.problem .card-tag { color: #EF4444; }
  .card.solution .card-tag { color: #10B981; }
  .card p {
    font-size: 22px;
    line-height: 1.45;
    color: #E5E7EB;
  }
  .pricing-box {
    background: #111827;
    border: 2px solid #10B981;
    border-radius: 24px;
    padding: 34px 40px;
    margin: 20px 0;
    box-shadow: 0 0 40px rgba(16, 185, 129, 0.12);
  }
  .price-big {
    font-size: 64px;
    font-weight: 800;
    color: #FFFFFF;
    letter-spacing: -2px;
    margin-bottom: 18px;
  }
  .price-period {
    font-size: 26px;
    color: #9CA3AF;
    font-weight: 600;
  }
  .benefits-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .benefits-list li {
    font-size: 22px;
    color: #D1D5DB;
    font-weight: 600;
  }
  .cta-banner {
    background: #10B981;
    color: #030712;
    padding: 20px 30px;
    border-radius: 16px;
    font-size: 24px;
    font-weight: 800;
    text-align: center;
    letter-spacing: 0.5px;
    box-shadow: 0 8px 30px rgba(16, 185, 129, 0.4);
    margin-top: 15px;
  }
  .footer-zone {
    border-top: 1px solid #1F2937;
    padding-top: 22px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .footer-text {
    font-size: 21px;
    color: #9CA3AF;
    font-weight: 600;
  }
  .footer-brand {
    font-size: 20px;
    font-weight: 800;
    color: #10B981;
    letter-spacing: 0.5px;
  }
</style>
</head>
<body>
  <div class="header-zone">
    <div class="badge">__BADGE__</div>
    <h1 class="title">__TITLE__</h1>
    <p class="subtitle">__SUBTITLE__</p>
  </div>
  <div class="main-zone">
    __CONTENT_HTML__
  </div>
  <div class="footer-zone">
    <div class="footer-text">__FOOTER__</div>
    <div class="footer-brand">⚡ SOFÍA AI</div>
  </div>
</body>
</html>
"""

def generate_slides():
    print(f"🎨 Generando las 5 placas del carrusel en {OUTPUT_DIR}...")
    for idx, slide in enumerate(SLIDES, 1):
        html_content = (
            HTML_TEMPLATE
            .replace("__BADGE__", slide["badge"])
            .replace("__TITLE__", slide["title"])
            .replace("__SUBTITLE__", slide["subtitle"])
            .replace("__CONTENT_HTML__", slide["content_html"])
            .replace("__FOOTER__", slide["footer"])
        )
        temp_html = f"/tmp/slide_{idx}.html"
        out_png = os.path.join(OUTPUT_DIR, slide["filename"])
        
        with open(temp_html, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        cmd = [
            "google-chrome",
            "--headless=new",
            "--disable-gpu",
            "--window-size=1080,1167",
            f"--screenshot={out_png}",
            temp_html
        ]
        subprocess.run(cmd, check=True)
        # Recortar exactamente a 1080x1080 para eliminar el offset de ventana headless y asegurar placa completa
        from PIL import Image
        im = Image.open(out_png)
        im_1080 = im.crop((0, 0, 1080, 1080))
        im_1080.save(out_png, optimize=True)
        size_kb = os.path.getsize(out_png) / 1024
        print(f"✅ Placa {idx}/5 lista y completa: {slide['filename']} ({size_kb:.1f} KB)")
        
    print(f"\n🎉 ¡Todas las placas fueron creadas con éxito en: {OUTPUT_DIR}!")

if __name__ == "__main__":
    generate_slides()
