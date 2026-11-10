import urllib.parse
from typing import Optional
from app.models.tenant import Tenant
from app.config.settings import settings

def generate_clinic_access_html(tenant: Tenant) -> str:
    """
    Generates a high-impact, printable HTML5 access card & QR poster for the clinic.
    Optimized for both mobile viewing (with instant copy buttons) and printing (A4 tabletop poster).
    """
    clean_agent_phone = "".join(filter(str.isdigit, str(settings.WHATSAPP_AGENT_PHONE or "5493435720312")))
    keyword = tenant.deep_link_keyword or tenant.slug
    direct_url = f"https://wa.me/{clean_agent_phone}?text={urllib.parse.quote(f'Hola quiero turno en {keyword}')}"
    encoded_url = urllib.parse.quote(direct_url)
    qr_img_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={encoded_url}&margin=15"

    biz_name = tenant.name
    owner_name = tenant.owner_name or "Equipo Profesional"
    rubro = tenant.business_type.capitalize()

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Turnos y Atención por WhatsApp — {biz_name}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background: #0f172a;
      color: #0f172a;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}
    .actions-bar {{
      display: flex;
      gap: 12px;
      margin-bottom: 24px;
      flex-wrap: wrap;
      justify-content: center;
    }}
    .btn {{
      background: #2563eb;
      color: white;
      border: none;
      padding: 12px 20px;
      border-radius: 10px;
      font-weight: 700;
      font-size: 14px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      text-decoration: none;
      transition: all 0.2s ease;
      box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
    }}
    .btn:hover {{
      background: #1d4ed8;
      transform: translateY(-2px);
    }}
    .btn-whatsapp {{
      background: #16a34a;
      box-shadow: 0 4px 12px rgba(22, 163, 74, 0.25);
    }}
    .btn-whatsapp:hover {{
      background: #15803d;
    }}
    .btn-secondary {{
      background: #334155;
      box-shadow: 0 4px 12px rgba(51, 65, 85, 0.25);
    }}
    .btn-secondary:hover {{
      background: #1e293b;
    }}

    /* POSTER CARD (A4 ASPECT) */
    .poster-card {{
      background: white;
      width: 100%;
      max-width: 480px;
      border-radius: 24px;
      padding: 44px 36px;
      text-align: center;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.4);
      border: 1px solid #e2e8f0;
      position: relative;
      overflow: hidden;
    }}
    .poster-card::before {{
      content: "";
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 8px;
      background: linear-gradient(90deg, #2563eb, #10b981);
    }}
    .badge {{
      display: inline-block;
      background: #eff6ff;
      color: #1d4ed8;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 1px;
      padding: 6px 14px;
      border-radius: 999px;
      margin-bottom: 16px;
    }}
    .clinic-title {{
      font-size: 26px;
      font-weight: 800;
      color: #0f172a;
      line-height: 1.25;
      margin-bottom: 6px;
    }}
    .clinic-subtitle {{
      font-size: 14px;
      color: #64748b;
      font-weight: 600;
      margin-bottom: 28px;
    }}
    .qr-frame {{
      background: #f8fafc;
      border: 2px dashed #cbd5e1;
      border-radius: 20px;
      padding: 16px;
      display: inline-block;
      margin-bottom: 24px;
      transition: transform 0.2s ease;
    }}
    .qr-frame img {{
      display: block;
      width: 240px;
      height: 240px;
      border-radius: 12px;
    }}
    .instructions {{
      font-size: 15px;
      font-weight: 700;
      color: #1e293b;
      line-height: 1.4;
      margin-bottom: 12px;
    }}
    .features {{
      display: flex;
      justify-content: center;
      gap: 16px;
      font-size: 12px;
      font-weight: 700;
      color: #475569;
      margin-top: 18px;
      padding-top: 18px;
      border-top: 1px solid #e2e8f0;
    }}
    .features span {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }}
    .toast {{
      position: fixed;
      bottom: 20px;
      background: #10b981;
      color: white;
      padding: 12px 24px;
      border-radius: 8px;
      font-weight: 700;
      display: none;
      box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    }}

    @media print {{
      body {{
        background: white !important;
        padding: 0 !important;
      }}
      .actions-bar, .toast {{
        display: none !important;
      }}
      .poster-card {{
        box-shadow: none !important;
        border: none !important;
        max-width: 100% !important;
        padding: 60px 40px !important;
      }}
      .qr-frame img {{
        width: 300px !important;
        height: 300px !important;
      }}
      .clinic-title {{
        font-size: 32px !important;
      }}
    }}
  </style>
</head>
<body>

  <!-- BOTONES DE ACCIÓN PARA EL MÉDICO / RECEPCIÓN -->
  <div class="actions-bar">
    <button class="btn" onclick="window.print()">
      🖨️ Imprimir Cartel para Mostrador
    </button>
    <button class="btn btn-secondary" onclick="copyLink()">
      📋 Copiar Link para Instagram / Redes
    </button>
    <a href="{direct_url}" class="btn btn-whatsapp" target="_blank">
      📲 Probar en WhatsApp Ahora
    </a>
  </div>

  <!-- CARTEL OFICIAL DE LA CLÍNICA -->
  <div class="poster-card">
    <div class="badge">🏥 Atención y Turnos 24 hs</div>
    <h1 class="clinic-title">{biz_name}</h1>
    <p class="clinic-subtitle">A cargo de {owner_name} • {rubro}</p>

    <div class="qr-frame">
      <img src="{qr_img_url}" alt="Código QR de WhatsApp para {biz_name}">
    </div>

    <p class="instructions">
      📸 <strong>Escaneá este código QR con tu celular</strong><br>
      para agendar tu turno o hacer consultas por WhatsApp.
    </p>

    <div class="features">
      <span>⚡ Turnos 24/7</span>
      <span>🔔 Recordatorios</span>
      <span>🛡️ Sin Esperas</span>
    </div>
  </div>

  <div id="toast" class="toast">✅ ¡Enlace copiado al portapapeles!</div>

  <script>
    function copyLink() {{
      const link = "{direct_url}";
      navigator.clipboard.writeText(link).then(() => {{
        const toast = document.getElementById("toast");
        toast.style.display = "block";
        setTimeout(() => {{ toast.style.display = "none"; }}, 2500);
      }}).catch(() => {{
        prompt("Copiá este enlace:", link);
      }});
    }}
  </script>
</body>
</html>
"""
