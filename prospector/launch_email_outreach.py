"""
Lanzador de prospección B2B por Email Corporativo para Súper Actualizador PRO.
Envía correos con autenticación SPF/DKIM desde javier@sof-ia.site vía Brevo SMTP,
con Reply-To directo a colomajavier@gmail.com.
"""
import os
import sys
import time
import argparse
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Optional, List

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal
from app.models.prospect import Prospect
from app.config.settings import settings

def build_email_content(merchant_name: str, contact_name: Optional[str] = None) -> tuple[str, str]:
    """Generates the plain text and responsive HTML content for cold B2B email outreach."""
    saludo_nombre = f" {contact_name.strip()}" if contact_name and contact_name.strip() else ""
    nombre_comercio = merchant_name.strip() if merchant_name else "tu negocio"

    subject = f"Actualización de listas y comparador de proveedores en 3 segundos ({nombre_comercio})"

    plain_text = f"""Hola{saludo_nombre}, ¿cómo estás?

Te escribo desde Sofía Tech porque encontramos tu comercio ({nombre_comercio}) y queríamos comentarte sobre una herramienta pensada para ahorrarte muchas horas y dinero: el Súper Actualizador PRO.

Si en tu negocio trabajan con varios proveedores y pierden tiempo recalculando aumentos de precios a mano en Excel o PDF, nuestro sistema hace esto:

1. Actualización en 3 segundos: Subís la lista tal cual te la envía el mayorista (sin editar nada) y te devuelve la lista nueva lista con los márgenes de ganancia que elijas.
2. Comparador automático de proveedores: Cruza listas para decirte al instante a quién te conviene comprarle cada artículo para pagar menos.

Podés entrar a nuestra web y probar el sistema durante 7 días gratis en tu computadora para familiarizarte con las 4 pestañas del software:
👉 https://sof-ia.site/actualizador

También podés ver los videos demostrativos en nuestro Instagram oficial:
👉 https://www.instagram.com/sof_ia.tech/

O si preferís una atención personalizada, podés responder directamente a este correo o escribirme por WhatsApp al +54 9 343 570-8612.

Estamos más que convencidos de que es una solución muy útil para hacerte ahorrar tiempo y dinero.

Un saludo cordial,
Javier Coloma
Asesor Técnico • Sofía Tech
WhatsApp: +54 9 343 570-8612
Web: https://sof-ia.site/actualizador
"""

    html_text = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{subject}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 15px; color: #222222; line-height: 1.6; max-width: 600px; margin: 0; padding: 15px 0;">
  <p>Hola<strong>{saludo_nombre}</strong>, ¿cómo estás?</p>
  
  <p>Te escribo porque encontramos la ficha de <strong>{nombre_comercio}</strong> y quería comentarte sobre una herramienta pensada para ahorrarte mucho tiempo y cuidar tus márgenes de ganancia: el <strong>Súper Actualizador PRO</strong>.</p>

  <p>Si en tu negocio trabajan con varios distribuidores o proveedores y pierden horas recalculando aumentos de precios a mano en Excel o PDF, el sistema hace dos cosas clave:</p>

  <p style="margin-left: 15px;">
    ⚡ <strong>1. Actualización en 3 segundos:</strong> Subís la lista tal cual te la manda el mayorista (sin editar nada) y te devuelve la lista nueva armada con los márgenes de ganancia que elijas.<br><br>
    🔍 <strong>2. Comparador automático de proveedores:</strong> Cruza listas de distintos distribuidores para decirte al instante a quién te conviene comprarle cada artículo para pagar menos.
  </p>

  <p>Podés entrar a nuestra web y <strong>probar el sistema durante 7 días gratis</strong> en tu computadora para que conozcas el software y te familiarices con las 4 pestañas del Actualizador PRO:<br>
  👉 <a href="https://sof-ia.site/actualizador" style="color: #0d9488; font-weight: bold; text-decoration: underline;">https://sof-ia.site/actualizador</a> (ahí podés ver la demo en video de 1 minuto y los precios transparentes).</p>

  <p>También podés entrar a nuestra página de Instagram para ver las demos y cómo lo usan otros comercios:<br>
  👉 <a href="https://www.instagram.com/sof_ia.tech/" style="color: #0d9488; text-decoration: underline;">https://www.instagram.com/sof_ia.tech/</a></p>

  <p>O si preferís, podés hablar directamente conmigo como asesor técnico respondiendo a este correo o escribiéndome por WhatsApp.</p>

  <p>Estamos más que convencidos de que es una solución muy útil para hacerte ahorrar tiempo y dinero.</p>

  <p style="margin-top: 30px; margin-bottom: 5px;">Un saludo cordial,</p>

  <!-- Firma Profesional Humana -->
  <table style="border-collapse: collapse; margin-top: 10px;">
    <tr>
      <td style="border-left: 3px solid #0d9488; padding-left: 12px;">
        <strong style="font-size: 16px; color: #111827;">Javier Coloma</strong><br>
        <span style="font-size: 13px; color: #0d9488; font-weight: 600;">Asesor Técnico • Sofía Tech</span><br>
        <span style="font-size: 13px; color: #4b5563;">
          📱 WhatsApp: <a href="https://wa.me/5493435708612" style="color: #111827; text-decoration: none; font-weight: bold;">+54 9 343 570-8612</a><br>
          🌐 Web: <a href="https://sof-ia.site/actualizador" style="color: #0d9488; text-decoration: none;">sof-ia.site/actualizador</a><br>
          📸 Instagram: <a href="https://www.instagram.com/sof_ia.tech/" style="color: #0d9488; text-decoration: none;">@sof_ia.tech</a>
        </span>
      </td>
    </tr>
  </table>

  <p style="font-size: 11px; color: #9ca3af; margin-top: 40px;">
    Si no deseas recibir más avisos sobre el Actualizador PRO, simplemente responde 'baja' a este correo.
  </p>
</body>
</html>"""

    return subject, plain_text, html_text


def send_email_via_brevo(to_email: str, subject: str, plain_text: str, html_text: str) -> bool:
    """Sends a single email through Brevo SMTP using configured credentials."""
    smtp_server = settings.BREVO_SMTP_SERVER
    smtp_port = settings.BREVO_SMTP_PORT
    smtp_user = settings.BREVO_SMTP_USER
    smtp_pass = settings.BREVO_SMTP_PASSWORD
    from_email = settings.BREVO_MAIL_FROM or "javier@sof-ia.site"
    reply_to = settings.BREVO_MAIL_REPLY_TO or "javiercolma82@gmail.com"

    if not smtp_user or not smtp_pass:
        print("❌ Error: Credenciales de Brevo SMTP no configuradas en settings/.env")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Javier Coloma | Sofía Tech <{from_email}>"
    msg["To"] = to_email
    msg["Reply-To"] = reply_to

    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_text, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            return True
    except Exception as e:
        print(f"   ❌ Error enviando email a {to_email}: {e}")
        return False


def run_email_campaign(
    limit: int = 15,
    dry_run: bool = False,
    delay_seconds: int = 15,
    test_to: Optional[str] = None
):
    """Executes the cold B2B email outreach campaign."""
    if test_to:
        print("=" * 75)
        print("🧪 MODO TEST: Enviando correo de prueba individual")
        print(f"📧 Destinatario: {test_to}")
        print("=" * 75)
        subj, plain, html = build_email_content(merchant_name="Ferretería Demo", contact_name="Javier")
        if dry_run:
            print(f"[DRY-RUN] Se enviaría correo con asunto: '{subj}'")
            return
        success = send_email_via_brevo(test_to, subj, plain, html)
        if success:
            print(f"✅ Correo de prueba enviado exitosamente a {test_to}")
        else:
            print(f"❌ Falló el envío de prueba a {test_to}")
        return

    db = SessionLocal()
    try:
        leads = db.query(Prospect).filter(
            Prospect.campaign == "actualizador_pro",
            Prospect.email != None,
            Prospect.email != ""
        ).order_by(Prospect.id.asc()).limit(limit).all()

        if not leads:
            print("ℹ️ No hay prospectos con email en la campaña 'actualizador_pro'.")
            return

        print("=" * 75)
        print("🚀 DESPACHADOR OFICIAL DE EMAIL B2B (Súper Actualizador PRO)")
        print(f"🎯 Total a procesar: {len(leads)} comercios con email")
        print(f"📧 Remitente: {settings.BREVO_MAIL_FROM} (Reply-To: {settings.BREVO_MAIL_REPLY_TO})")
        print(f"⏱️ Intervalo entre envíos: {delay_seconds}s | Modo Dry-Run: {dry_run}")
        print("=" * 75)

        sent_count = 0
        error_count = 0

        for idx, lead in enumerate(leads, 1):
            target_email = lead.email.strip()
            print(f"\n[{idx}/{len(leads)}] {lead.name} ({lead.city or 'S/D'}) | Email: {target_email}")

            subj, plain, html = build_email_content(merchant_name=lead.name, contact_name=lead.contact_name)

            if dry_run:
                print(f"   [DRY-RUN] Se enviaría correo a {target_email} con asunto: '{subj}'")
                sent_count += 1
                continue

            success = send_email_via_brevo(target_email, subj, plain, html)
            if success:
                lead.updated_at = datetime.now(timezone.utc)
                db.commit()
                print(f"   ✅ Email enviado con éxito a {target_email}.")
                sent_count += 1
            else:
                error_count += 1

            if idx < len(leads) and not dry_run:
                print(f"   ⏳ Esperando {delay_seconds}s para cuidar reputación de dominio...")
                time.sleep(delay_seconds)

        print("\n" + "=" * 75)
        print(f"🏁 Campaña de Email finalizada: {sent_count} enviados | {error_count} errores")
        print("=" * 75)

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lanzador de prospección B2B por Email para Actualizador Pro")
    parser.add_argument("--limit", type=int, default=15, help="Cantidad de comercios con email a enviar (default: 15)")
    parser.add_argument("--dry-run", action="store_true", help="Simula el envío sin disparar correos reales")
    parser.add_argument("--delay", type=int, default=15, help="Segundos entre envíos (default: 15)")
    parser.add_argument("--test-to", type=str, default=None, help="Envía un correo de prueba a esta casilla específica")

    args = parser.parse_args()
    run_email_campaign(
        limit=args.limit,
        dry_run=args.dry_run,
        delay_seconds=args.delay,
        test_to=args.test_to
    )
