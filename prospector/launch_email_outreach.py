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

def build_email_content(merchant_name: str, contact_name: Optional[str] = None) -> tuple[str, str, str]:
    """Generates ultra-clean 1-on-1 conversational B2B email to land in Gmail Primary inbox."""
    saludo_nombre = f" {contact_name.strip()}" if contact_name and contact_name.strip() else ""
    nombre_comercio = merchant_name.strip() if merchant_name else "tu comercio"

    subject = f"Consulta sobre listas de precios ({nombre_comercio})"

    plain_text = f"""Hola{saludo_nombre}, como estas?

Te escribo porque encontre la ficha de {nombre_comercio} y queria hacerte una consulta: como se estan manejando hoy cuando los distribuidores o proveedores les mandan listas en Excel o PDF con aumentos de precios?

Desarrollamos un programa para Windows (Super Actualizador PRO) pensado para comercios de la zona: subis la lista tal cual te la manda el mayorista y en pocos segundos te calcula todos tus precios de venta con tus margenes de ganancia, ademas de comparar entre varios proveedores para saber quien tiene el precio mas conveniente en cada articulo.

Podes probarlo durante 7 dias en tu computadora para conocerlo y familiarizarte con las 4 pestanas del sistema:
https://sof-ia.site/actualizador

Tambien podes ver las demostraciones en video en nuestro Instagram oficial:
https://www.instagram.com/sof_ia.tech/

O si preferis, podes responderme a este correo o escribirme directamente por WhatsApp al +54 9 343 570-8612.

Estamos convencidos de que es una solucion muy util para hacerte ahorrar tiempo y dinero.

Un saludo cordial,
Javier Coloma
Asesor Tecnico • Sofia Tech
WhatsApp: +54 9 343 570-8612
Web: https://sof-ia.site/actualizador
"""

    html_text = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
</head>
<body style="font-family: Arial, Helvetica, sans-serif; font-size: 15px; color: #1f2937; line-height: 1.6; margin: 0; padding: 10px 0;">
  <p>Hola<strong>{saludo_nombre}</strong>, ¿cómo estás?</p>
  
  <p>Te escribo porque encontré la ficha de <strong>{nombre_comercio}</strong> y quería hacerte una consulta: ¿cómo se están manejando hoy cuando los distribuidores o proveedores les mandan listas en Excel o PDF con aumentos de precios?</p>

  <p>Desarrollamos un programa para Windows (<strong>Súper Actualizador PRO</strong>) pensado para comercios de la zona: subís la lista tal cual te la manda el mayorista y en pocos segundos te calcula todos tus precios de venta con tus márgenes de ganancia, además de comparar entre varios proveedores para saber quién tiene el precio más conveniente en cada artículo.</p>

  <p>Podés probarlo durante 7 días en tu computadora para conocerlo y familiarizarte con las 4 pestañas del sistema:<br>
  <a href="https://sof-ia.site/actualizador" style="color: #0f766e;">https://sof-ia.site/actualizador</a> (ahí podés ver la demo en video de 1 minuto y los precios transparentes).</p>

  <p>También podés ver las demostraciones en video en nuestro Instagram oficial:<br>
  <a href="https://www.instagram.com/sof_ia.tech/" style="color: #0f766e;">https://www.instagram.com/sof_ia.tech/</a></p>

  <p>O también podés hablar directamente conmigo como asesor técnico respondiendo a este correo o escribiéndome por WhatsApp.</p>

  <p>Estamos convencidos de que es una solución muy útil para hacerte ahorrar tiempo y dinero.</p>

  <p style="margin-top: 25px; margin-bottom: 5px;">Un saludo cordial,</p>
  <p style="margin-top: 0; line-height: 1.4;">
    <strong>Javier Coloma</strong><br>
    <span style="color: #0f766e; font-size: 14px;">Asesor Técnico • Sofía Tech</span><br>
    <span style="font-size: 13px; color: #4b5563;">
      WhatsApp: <a href="https://wa.me/5493435708612" style="color: #111827; text-decoration: none;">+54 9 343 570-8612</a><br>
      Web: <a href="https://sof-ia.site/actualizador" style="color: #0f766e; text-decoration: none;">sof-ia.site/actualizador</a>
    </span>
  </p>
</body>
</html>"""

    return subject, plain_text, html_text

    return subject, plain_text, html_text


def send_email_via_brevo(to_email: str, subject: str, plain_text: str, html_text: Optional[str] = None) -> bool:
    """Sends an email through Brevo SMTP using authenticated domain javier@sof-ia.site."""
    smtp_server = settings.BREVO_SMTP_SERVER
    smtp_port = settings.BREVO_SMTP_PORT
    smtp_user = settings.BREVO_SMTP_USER
    smtp_pass = settings.BREVO_SMTP_PASSWORD
    from_email = settings.BREVO_MAIL_FROM or "javier@sof-ia.site"
    reply_to = settings.BREVO_MAIL_REPLY_TO or "javiercolma82@gmail.com"

    if not smtp_user or not smtp_pass:
        print("❌ Error: Credenciales de Brevo SMTP no configuradas en settings/.env")
        return False

    if html_text:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Javier Coloma | Sofía Tech <{from_email}>"
        msg["To"] = to_email
        msg["Reply-To"] = reply_to
        msg.attach(MIMEText(plain_text, "plain", "utf-8"))
        msg.attach(MIMEText(html_text, "html", "utf-8"))
    else:
        msg = MIMEText(plain_text, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = f"Javier Coloma <{from_email}>"
        msg["To"] = to_email
        msg["Reply-To"] = reply_to

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            return True
    except Exception as e:
        print(f"   ❌ Error enviando email vía Brevo a {to_email}: {e}")
        return False


def send_email_via_gmail(to_email: str, subject: str, plain_text: str) -> bool:
    """Sends an email through native Google SMTP (100% Primary Inbox for @gmail.com recipients)."""
    gmail_user = settings.MAIL_USERNAME
    gmail_pass = settings.MAIL_PASSWORD

    if not gmail_user or not gmail_pass:
        print("❌ Error: Credenciales de Gmail SMTP no configuradas en settings/.env")
        return False

    msg = MIMEText(plain_text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"Javier Coloma <{gmail_user}>"
    msg["To"] = to_email
    msg["Reply-To"] = gmail_user

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.send_message(msg)
            return True
    except Exception as e:
        print(f"   ❌ Error enviando email vía Gmail SMTP a {to_email}: {e}")
        return False


def send_email_smart(to_email: str, subject: str, plain_text: str, html_text: Optional[str] = None, engine: str = "auto") -> bool:
    """Smart routing: Sends @gmail.com leads via Google SMTP (Primary inbox), and corporate leads via Brevo."""
    is_gmail_recipient = "@gmail.com" in to_email.lower()

    if engine == "gmail" or (engine == "auto" and is_gmail_recipient):
        print("      [Motor: Gmail Directo (Bypass Promociones)]")
        return send_email_via_gmail(to_email, subject, plain_text)
    else:
        print("      [Motor: Brevo Corporativo javier@sof-ia.site (SPF/DKIM)]")
        return send_email_via_brevo(to_email, subject, plain_text, html_text)


def run_email_campaign(
    limit: int = 15,
    dry_run: bool = False,
    delay_seconds: int = 15,
    test_to: Optional[str] = None,
    engine: str = "auto",
    plain_only: bool = False
):
    """Executes the cold B2B email outreach campaign."""
    if test_to:
        print("=" * 75)
        print("🧪 MODO TEST: Enviando correo de prueba individual")
        print(f"📧 Destinatario: {test_to} | Motor: {engine} | Solo texto: {plain_only}")
        print("=" * 75)
        subj, plain, html = build_email_content(merchant_name="Ferretería Demo", contact_name="Javier")
        html_payload = None if plain_only else html
        if dry_run:
            print(f"[DRY-RUN] Se enviaría correo con asunto: '{subj}'")
            return
        success = send_email_smart(test_to, subj, plain, html_payload, engine=engine)
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
        print(f"📧 Motor de envío: {engine.upper()} (Auto-routing activo)")
        print(f"⏱️ Intervalo entre envíos: {delay_seconds}s | Modo Dry-Run: {dry_run}")
        print("=" * 75)

        sent_count = 0
        error_count = 0

        for idx, lead in enumerate(leads, 1):
            target_email = lead.email.strip()
            print(f"\n[{idx}/{len(leads)}] {lead.name} ({lead.city or 'S/D'}) | Email: {target_email}")

            subj, plain, html = build_email_content(merchant_name=lead.name, contact_name=lead.contact_name)
            html_payload = None if plain_only else html

            if dry_run:
                print(f"   [DRY-RUN] Se enviaría correo a {target_email} con asunto: '{subj}'")
                sent_count += 1
                continue

            success = send_email_smart(target_email, subj, plain, html_payload, engine=engine)
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
    parser.add_argument("--engine", type=str, default="auto", choices=["auto", "brevo", "gmail"], help="Motor de envío (default: auto)")
    parser.add_argument("--plain-only", action="store_true", help="Envía solo texto plano sin HTML para maximizar entrada a Principal")

    args = parser.parse_args()
    run_email_campaign(
        limit=args.limit,
        dry_run=args.dry_run,
        delay_seconds=args.delay,
        test_to=args.test_to,
        engine=args.engine,
        plain_only=args.plain_only
    )
