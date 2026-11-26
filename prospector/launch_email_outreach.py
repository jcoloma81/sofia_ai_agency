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
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #1e293b; line-height: 1.6;">
  <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;">
    
    <!-- Encabezado Estético Oficial -->
    <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 30px 25px; text-align: center; border-bottom: 3px solid #10b981;">
      <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">Súper Actualizador <span style="color: #10b981;">PRO</span></h1>
      <p style="color: #94a3b8; margin: 6px 0 0 0; font-size: 14px; font-weight: 500;">Sofía Tech • Soluciones de Automatización para Comercios</p>
    </div>

    <!-- Cuerpo del Mensaje -->
    <div style="padding: 30px 25px;">
      <p style="font-size: 16px; margin-top: 0;">Hola<strong>{saludo_nombre}</strong>, ¿cómo estás?</p>
      
      <p style="font-size: 15px; color: #334155;">
        Te escribimos porque encontramos la ficha de <strong>{nombre_comercio}</strong> y queríamos comentarte sobre una herramienta pensada exclusivamente para hacerte ahorrar tiempo y proteger tus márgenes comerciales: el <strong>Súper Actualizador PRO</strong>.
      </p>

      <p style="font-size: 15px; color: #334155;">
        Si en tu local manejan varios proveedores y pierden horas los fines de semana recalculando aumentos de precios a mano en Excel o PDF, nuestro sistema resuelve dos problemas clave:
      </p>

      <!-- Bloque de Beneficios -->
      <div style="background-color: #f1f5f9; border-radius: 8px; padding: 18px 20px; margin: 20px 0;">
        <div style="margin-bottom: 14px;">
          <strong style="color: #0f172a; font-size: 15px;">⚡ 1. Actualización en 3 segundos:</strong>
          <p style="margin: 4px 0 0 0; font-size: 14px; color: #475569;">Subís la lista tal cual te la manda el mayorista (sin editar nada) y te devuelve la lista lista con los márgenes de ganancia que elijas.</p>
        </div>
        <div>
          <strong style="color: #0f172a; font-size: 15px;">🔍 2. Comparador automático de proveedores:</strong>
          <p style="margin: 4px 0 0 0; font-size: 14px; color: #475569;">Cruza listas de distintos distribuidores para decirte al instante a quién te conviene comprarle cada producto más barato.</p>
        </div>
      </div>

      <!-- Llamado a la Acción (CTA) -->
      <div style="background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; padding: 18px; text-align: center; margin: 25px 0;">
        <p style="color: #065f46; font-size: 15px; font-weight: 700; margin: 0 0 12px 0;">🎁 Prueba gratis por 7 días en tu computadora</p>
        <p style="color: #047857; font-size: 13px; margin: 0 0 16px 0;">Podés descargarlo y probarlo sin compromiso para familiarizarte con las 4 pestañas del sistema.</p>
        <a href="https://sof-ia.site/actualizador" target="_blank" style="background-color: #10b981; color: #ffffff; text-decoration: none; padding: 12px 28px; border-radius: 6px; font-weight: 700; font-size: 15px; display: inline-block; box-shadow: 0 4px 10px rgba(16,185,129,0.3);">
          Ver Video Demo y Precios →
        </a>
      </div>

      <p style="font-size: 14px; color: #475569;">
        También podés seguirnos en Instagram para ver demos y tutoriales de cómo lo usan otros negocios:<br>
        👉 <a href="https://www.instagram.com/sof_ia.tech/" target="_blank" style="color: #10b981; font-weight: 600; text-decoration: none;">@sof_ia.tech en Instagram</a>
      </p>

      <p style="font-size: 14px; color: #475569;">
        O si preferís una atención personalizada, podés responder directamente a este correo o hablar conmigo por WhatsApp.
      </p>

      <p style="font-size: 14px; color: #334155; font-weight: 600; margin-top: 25px;">
        Estamos más que convencidos de que es una solución muy útil para hacerte ahorrar tiempo y dinero.
      </p>

      <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 25px 0;">

      <!-- Firma Oficial Javier Coloma -->
      <table style="width: 100%; border-collapse: collapse;">
        <tr>
          <td style="vertical-align: middle;">
            <p style="margin: 0; font-size: 15px; font-weight: 800; color: #0f172a;">Javier Coloma</p>
            <p style="margin: 2px 0 6px 0; font-size: 13px; color: #10b981; font-weight: 600;">Asesor Técnico • Sofía Tech</p>
            <p style="margin: 0; font-size: 13px; color: #64748b;">
              📱 WhatsApp: <a href="https://wa.me/5493435708612" style="color: #0f172a; text-decoration: none; font-weight: 600;">+54 9 343 570-8612</a><br>
              🌐 Web Oficial: <a href="https://sof-ia.site/actualizador" style="color: #10b981; text-decoration: none;">sof-ia.site/actualizador</a><br>
              📸 Instagram: <a href="https://www.instagram.com/sof_ia.tech/" style="color: #10b981; text-decoration: none;">@sof_ia.tech</a>
            </p>
          </td>
        </tr>
      </table>

    </div>

    <!-- Pie Antispam Oficial -->
    <div style="background-color: #f8fafc; padding: 15px 25px; text-align: center; border-top: 1px solid #e2e8f0; font-size: 11px; color: #94a3b8;">
      <p style="margin: 0;">Sofía Tech • Paraná, Entre Ríos, Argentina.</p>
      <p style="margin: 4px 0 0 0;">Has recibido esta información como contacto comercial de {nombre_comercio}. Si no deseas recibir más avisos, simplemente responde 'baja' a este correo.</p>
    </div>

  </div>
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
