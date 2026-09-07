import logging
from datetime import datetime
from typing import Optional
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from app.config.settings import settings

logger = logging.getLogger(__name__)

def get_mail_client() -> Optional[FastMail]:
    """Builds and returns FastMail client if credentials are configured."""
    if not settings.MAIL_USERNAME or not settings.MAIL_PASSWORD:
        logger.info("[AlertService] Email credentials not fully configured. Email alerts will be logged.")
        return None
    try:
        conf = ConnectionConfig(
            MAIL_USERNAME=settings.MAIL_USERNAME,
            MAIL_PASSWORD=settings.MAIL_PASSWORD,
            MAIL_FROM=settings.MAIL_FROM or settings.MAIL_USERNAME,
            MAIL_PORT=settings.MAIL_PORT,
            MAIL_SERVER=settings.MAIL_SERVER,
            MAIL_STARTTLS=settings.MAIL_STARTTLS,
            MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
            USE_CREDENTIALS=True,
            VALIDATE_CERTS=True,
            MAIL_FROM_NAME="Sofía AI Agency"
        )
        return FastMail(conf)
    except Exception as e:
        logger.error(f"[AlertService] Failed to initialize FastMail: {e}")
        return None

async def send_email_alert(
    subject: str,
    recipient: str,
    html_content: str
) -> bool:
    """Sends an HTML email alert using FastMail."""
    if not recipient or "@" not in recipient:
        logger.warning(f"[AlertService] Invalid recipient email '{recipient}'")
        return False

    client = get_mail_client()
    if not client:
        logger.info(f"[EMAIL SIMULATION] Alert to {recipient}: Subject '{subject}'")
        return True

    message = MessageSchema(
        subject=subject,
        recipients=[recipient],
        body=html_content,
        subtype=MessageType.html
    )

    try:
        await client.send_message(message)
        logger.info(f"[AlertService] Email alert successfully dispatched to {recipient}")
        return True
    except Exception as e:
        logger.error(f"[AlertService] FAILED to send email alert to {recipient}: {e}")
        return False

def build_meeting_html_email(
    prospect_name: str,
    contact_name: Optional[str],
    phone: str,
    city: Optional[str],
    meeting_details: str,
    last_message: str,
    campaign: str = "ai_agency"
) -> str:
    """Generates corporate HTML email template for meeting alert."""
    now_str = datetime.now().strftime("%d/%m/%Y a las %H:%M hs")
    contact_str = contact_name or "Dueño / Responsable"
    city_str = city or "Entre Ríos / Santa Fe"
    campaign_title = "Sofía AI Agency (Agente B2B Comercial)" if campaign == "ai_agency" else "Air Control"
    action_text = (
        "Llamalo puntual para presentarle la demo en vivo del Agente Comercial con IA (Cupo especial: Setup $0 bonificado + $70.000-$100.000/mes abono)."
        if campaign == "ai_agency"
        else "Agendalo en tu calendario y tené a mano el dossier interactivo."
    )

    from app.services.calendar import generate_google_calendar_link
    cal_url = generate_google_calendar_link(
        summary=f"🎯 Demo Sofía IA: {prospect_name}",
        description=f"Reunión acordada por Sofía B2B SDR.\nContacto: {contact_str}\nTeléfono: +{phone}\nLocalidad: {city_str}\nHorario pactado: {meeting_details}\nÚltimo mensaje: {last_message}",
        location=f"{city_str} • Videollamada"
    )

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; margin: 0; padding: 24px; color: #f8fafc; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #1e293b; border-radius: 16px; overflow: hidden; border: 1px solid #334155; box-shadow: 0 10px 25px rgba(0,0,0,0.3); }}
            .header {{ background: linear-gradient(135deg, #6366f1 0%, #3b82f6 100%); color: #ffffff; padding: 28px; text-align: center; }}
            .badge {{ background: #10b981; color: white; padding: 6px 14px; border-radius: 9999px; font-weight: bold; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block; }}
            .content {{ padding: 28px; line-height: 1.6; color: #e2e8f0; }}
            .data-card {{ background: #0f172a; border-radius: 12px; padding: 20px; margin: 20px 0; border: 1px solid #334155; }}
            .data-row {{ margin-bottom: 10px; font-size: 15px; }}
            .data-row b {{ color: #94a3b8; width: 140px; display: inline-block; }}
            .data-val {{ color: #ffffff; font-weight: 500; }}
            .highlight-time {{ color: #38bdf8; font-weight: bold; font-size: 17px; }}
            .quote {{ background: #1e1e38; border-left: 4px solid #6366f1; padding: 14px 16px; font-style: italic; margin: 18px 0; border-radius: 6px; color: #cbd5e1; }}
            .action-box {{ background: #14532d; border: 1px solid #22c55e; border-radius: 10px; padding: 14px 18px; margin-top: 20px; color: #bbf7d0; font-size: 14px; }}
            .footer {{ background: #0b0f19; padding: 18px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #334155; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <span class="badge">🎯 NUEVA CITA COMERCIAL</span>
                <h2 style="margin: 12px 0 0 0; font-size: 24px;">¡Reunión Confirmada por Sofía!</h2>
                <p style="margin: 6px 0 0 0; font-size: 14px; opacity: 0.9;">{campaign_title}</p>
            </div>
            <div class="content">
                <p style="font-size: 16px;">Hola <strong>Javier</strong>, Sofía acaba de coordinar una nueva cita con un lead calificado:</p>
                <div class="data-card">
                    <div class="data-row"><b>Empresa / Lead:</b> <span class="data-val">{prospect_name}</span></div>
                    <div class="data-row"><b>Contacto:</b> <span class="data-val">{contact_str}</span></div>
                    <div class="data-row"><b>WhatsApp:</b> <a href="https://wa.me/{phone}" style="color: #38bdf8; text-decoration: none;" class="data-val">+{phone}</a></div>
                    <div class="data-row"><b>Localidad:</b> <span class="data-val">{city_str}</span></div>
                    <div class="data-row"><b>Horario Pactado:</b> <span class="highlight-time">{meeting_details}</span></div>
                </div>
                <p style="margin-bottom: 6px; font-size: 14px; color: #94a3b8;"><b>Último mensaje recibido del cliente:</b></p>
                <div class="quote">"{last_message}"</div>
                <div class="action-box">
                    👉 <strong>Próximo paso sugerido:</strong> {action_text}
                </div>
                <div style="margin-top: 20px; text-align: center;">
                    <a href="{cal_url}" target="_blank" style="display: inline-block; background: #10b981; color: #ffffff; font-weight: bold; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-size: 14px; box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);">
                        📅 Añadir a mi Google Calendar
                    </a>
                </div>
            </div>
            <div class="footer">
                Sofía AI Agency • Prospección B2B Autónoma • {now_str}
            </div>
        </div>
    </body>
    </html>
    """

def build_order_html_email(
    client_name: str,
    contact_name: Optional[str],
    phone: str,
    city: Optional[str],
    order_items: list,
    total_formatted: str,
    delivery_notes: Optional[str] = None
) -> str:
    """Generates corporate HTML email template for new order alert."""
    now_str = datetime.now().strftime("%d/%m/%Y a las %H:%M hs")
    contact_str = contact_name or "Comercio / Encargado"
    city_str = city or "No especificada"

    items_html = ""
    for item in order_items:
        items_html += f"""
        <tr style="border-bottom: 1px solid #334155;">
            <td style="padding: 10px; color: #ffffff;">{item.quantity}x {item.product.name}</td>
            <td style="padding: 10px; color: #94a3b8; text-align: center;">{item.product.presentation}</td>
            <td style="padding: 10px; color: #94a3b8; text-align: right;">{item.product.formatted_price()}</td>
            <td style="padding: 10px; color: #38bdf8; font-weight: bold; text-align: right;">{item.formatted_subtotal()}</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; margin: 0; padding: 24px; color: #f8fafc; }}
            .container {{ max-width: 650px; margin: 0 auto; background: #1e293b; border-radius: 16px; overflow: hidden; border: 1px solid #334155; box-shadow: 0 10px 25px rgba(0,0,0,0.3); }}
            .header {{ background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: #ffffff; padding: 28px; text-align: center; }}
            .badge {{ background: #0f172a; color: #34d399; padding: 6px 14px; border-radius: 9999px; font-weight: bold; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block; }}
            .content {{ padding: 28px; line-height: 1.6; color: #e2e8f0; }}
            .data-card {{ background: #0f172a; border-radius: 12px; padding: 20px; margin: 20px 0; border: 1px solid #334155; }}
            .data-row {{ margin-bottom: 10px; font-size: 15px; }}
            .data-row b {{ color: #94a3b8; width: 140px; display: inline-block; }}
            .data-val {{ color: #ffffff; font-weight: 500; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }}
            th {{ background: #0f172a; padding: 10px; color: #94a3b8; text-align: left; border-bottom: 2px solid #334155; }}
            .total-box {{ background: #064e3b; border: 2px solid #10b981; border-radius: 10px; padding: 16px; margin-top: 20px; text-align: right; }}
            .footer {{ background: #0b0f19; padding: 18px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #334155; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <span class="badge">📦 NUEVO PEDIDO CONFIRMADO</span>
                <h2 style="margin: 12px 0 0 0; font-size: 24px;">¡Pedido Listo para Despacho!</h2>
            </div>
            <div class="content">
                <p style="font-size: 16px;">Hola, <strong>Sofía</strong> acaba de cerrar un nuevo pedido de mercadería:</p>
                <div class="data-card">
                    <div class="data-row"><b>Cliente / Razón:</b> <span class="data-val">{client_name}</span></div>
                    <div class="data-row"><b>Contacto:</b> <span class="data-val">{contact_str}</span></div>
                    <div class="data-row"><b>WhatsApp:</b> <a href="https://wa.me/{phone}" style="color: #38bdf8; text-decoration: none;" class="data-val">+{phone}</a></div>
                    <div class="data-row"><b>Localidad / Zona:</b> <span class="data-val">{city_str}</span></div>
                </div>

                <h3 style="color: #ffffff; margin-top: 24px; margin-bottom: 8px;">Detalle de Mercadería:</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Producto</th>
                            <th style="text-align: center;">Bulto</th>
                            <th style="text-align: right;">Precio Unit.</th>
                            <th style="text-align: right;">Subtotal</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items_html}
                    </tbody>
                </table>

                <div class="total-box">
                    <span style="font-size: 16px; color: #a7f3d0; margin-right: 15px;">TOTAL ESTIMADO:</span>
                    <span style="font-size: 24px; font-weight: bold; color: #ffffff;">{total_formatted}</span>
                </div>

                <div style="margin-top: 25px; text-align: center;">
                    <a href="https://wa.me/{phone}" target="_blank" style="display: inline-block; background: #25d366; color: #ffffff; font-weight: bold; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-size: 14px; box-shadow: 0 4px 12px rgba(37, 211, 102, 0.3);">
                        💬 Abrir Chat con el Cliente
                    </a>
                </div>
            </div>
            <div class="footer">
                Sofía AI Agency • Sistema de Ventas y Despacho Automatizado • {now_str}
            </div>
        </div>
    </body>
    </html>
    """
