import asyncio
import logging
import re
from typing import Optional, Any, List
import httpx
from datetime import datetime
from app.config.settings import settings
from app.services.alerts import send_email_alert, build_meeting_html_email

logger = logging.getLogger(__name__)

async def send_whatsapp_message(to_phone: str, text: str) -> bool:
    """
    Sends a WhatsApp message via Official Meta WhatsApp Cloud API (Primary Enterprise Gateway),
    or falls back to Whapi.Cloud, or simulation log.
    """
    clean_phone = "".join(filter(str.isdigit, to_phone))

    # 1. Official Meta WhatsApp Cloud API (Primary Enterprise Gateway)
    if settings.META_ACCESS_TOKEN and settings.META_PHONE_NUMBER_ID:
        meta_url = f"https://graph.facebook.com/v20.0/{settings.META_PHONE_NUMBER_ID}/messages"
        meta_headers = {
            "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        meta_payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {"preview_url": False, "body": text}
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(meta_url, json=meta_payload, headers=meta_headers)
                if res.status_code in [200, 201]:
                    logger.info(f"✅ Meta WhatsApp Cloud API message sent successfully to {clean_phone}")
                    return True
                else:
                    logger.warning(f"Meta Cloud API returned status {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Error calling Meta WhatsApp Cloud API: {e}")

    # 2. Whapi.Cloud Gateway Fallback
    api_url = settings.WHATSAPP_API_URL
    api_token = settings.WHATSAPP_API_TOKEN

    if not api_url or not api_token:
        logger.info(f"[WHATSAPP SIMULATION] Message to {clean_phone}: {text}")
        return True

    try:
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }

        # Whapi Cloud format
        if "whapi.cloud" in api_url:
            endpoint = f"{api_url.rstrip('/')}/messages/text"
            payload = {
                "to": clean_phone,
                "body": text
            }
        else:
            endpoint = f"{api_url.rstrip('/')}/send-message"
            payload = {
                "phone": clean_phone,
                "message": text
            }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(endpoint, json=payload, headers=headers)
            if res.status_code in [200, 201]:
                logger.info(f"WhatsApp message successfully sent to {clean_phone}")
                return True
            else:
                logger.warning(f"WhatsApp Gateway ({endpoint}) returned status {res.status_code}: {res.text}")
                return False
    except Exception as e:
        logger.error(f"Error sending WhatsApp message to {clean_phone}: {e}")
        return False

async def send_whatsapp_document(
    to_phone: str,
    document_url: str,
    filename: str = "Propuesta_Sofia_IA.pdf",
    caption: Optional[str] = None
) -> bool:
    """
    Sends a PDF or document through Meta WhatsApp Cloud API or Whapi.Cloud.
    """
    clean_phone = "".join(filter(str.isdigit, to_phone))

    # 1. Official Meta WhatsApp Cloud API (Primary Enterprise Gateway)
    if settings.META_ACCESS_TOKEN and settings.META_PHONE_NUMBER_ID:
        meta_url = f"https://graph.facebook.com/v20.0/{settings.META_PHONE_NUMBER_ID}/messages"
        meta_headers = {
            "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        meta_payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "document",
            "document": {
                "link": document_url,
                "filename": filename
            }
        }
        if caption:
            meta_payload["document"]["caption"] = caption

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(meta_url, json=meta_payload, headers=meta_headers)
                if res.status_code in [200, 201]:
                    logger.info(f"✅ Meta WhatsApp Cloud API document sent successfully to {clean_phone}")
                    return True
                else:
                    logger.warning(f"Meta Cloud API document returned status {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Error sending document via Meta WhatsApp Cloud API: {e}")

    # 2. Whapi.Cloud Fallback
    api_url = settings.WHATSAPP_API_URL
    api_token = settings.WHATSAPP_API_TOKEN

    if not api_url or not api_token:
        logger.info(f"[WHATSAPP SIMULATION] Document {filename} to {clean_phone} via {document_url}")
        return True

    try:
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }

        endpoint = f"{api_url.rstrip('/')}/messages/document"
        payload = {
            "to": clean_phone,
            "media": document_url,
            "filename": filename
        }
        if caption:
            payload["caption"] = caption

        async with httpx.AsyncClient(timeout=25.0) as client:
            res = await client.post(endpoint, json=payload, headers=headers)
            if res.status_code in [200, 201]:
                logger.info(f"WhatsApp PDF document successfully sent to {clean_phone}")
                return True
            else:
                logger.warning(f"WhatsApp Document Gateway returned status {res.status_code}: {res.text}")
                return False
    except Exception as e:
        logger.error(f"Error sending WhatsApp document to {clean_phone}: {e}")
        return False

async def notify_javier_meeting_scheduled(
    prospect_name: str,
    contact_name: Optional[str],
    phone: str,
    city: Optional[str],
    meeting_details: str,
    last_message: str,
    campaign: str = "ai_agency"
) -> None:
    """
    Dual Alert System for Javier Coloma:
    1. WhatsApp immediate message to his private line (+54 9 343 453-6447).
    2. High-priority corporate HTML email to his inbox.
    """
    alert_phone = settings.WHATSAPP_ALERT_PHONE or "5493434536447"
    contact_str = contact_name or "Dueño / Administración"
    city_str = city or "Entre Ríos / Santa Fe"

    from app.services.calendar import generate_google_calendar_link
    cal_link = generate_google_calendar_link(
        summary=f"🎯 Demo Sofía IA: {prospect_name}",
        description=f"Reunión acordada por Sofía B2B SDR.\nContacto: {contact_str}\nTeléfono: +{phone}\nLocalidad: {city_str}\nHorario pactado: {meeting_details}\nÚltimo mensaje: {last_message}",
        location=f"{city_str} • Videollamada"
    )

    # 1. WhatsApp Alert
    if campaign == "ai_agency":
        wa_alert_text = (
            f"🔔 *¡NUEVA REUNIÓN CONFIRMADA! (Sofía AI Agency)*\n\n"
            f"🏢 *Empresa / Distribuidora:* {prospect_name}\n"
            f"👤 *Contacto:* {contact_str}\n"
            f"📱 *Teléfono:* +{phone}\n"
            f"📍 *Localidad:* {city_str}\n"
            f"⏰ *Horario pactado:* {meeting_details}\n"
            f"💬 *Último mensaje del cliente:* \"{last_message}\"\n\n"
            f"👉 *Acción:* Llamalo en ese horario para hacerle la demo de Sofía (Cupo especial: Setup $0 bonificado + $70.000-$100.000/mes de abono).\n\n"
            f"📅 *Agendar en 1 clic en Google Calendar:*\n{cal_link}"
        )
    else:
        wa_alert_text = (
            f"🔔 *¡NUEVA REUNIÓN CONFIRMADA! (Air Control)*\n\n"
            f"🏨 *Complejo:* {prospect_name}\n"
            f"👤 *Contacto:* {contact_str}\n"
            f"📱 *Teléfono:* +{phone}\n"
            f"📍 *Localidad:* {city_str}\n"
            f"⏰ *Horario pactado:* {meeting_details}\n"
            f"💬 *Último mensaje del cliente:* \"{last_message}\"\n\n"
            f"👉 *Acción:* Llamalo en ese horario para la reunión acordada.\n\n"
            f"📅 *Agendar en 1 clic en Google Calendar:*\n{cal_link}"
        )

    await send_whatsapp_message(to_phone=alert_phone, text=wa_alert_text)
    logger.info(f"WhatsApp appointment notification dispatched to Javier ({alert_phone}) for {prospect_name}")

    # 2. Corporate HTML Email Alert
    try:
        email_html = build_meeting_html_email(
            prospect_name=prospect_name,
            contact_name=contact_name,
            phone=phone,
            city=city,
            meeting_details=meeting_details,
            last_message=last_message,
            campaign=campaign
        )
        campaign_title = "Sofía AI Agency" if campaign == "ai_agency" else "Air Control"
        recipient_email = settings.MAIL_USERNAME or settings.MAIL_FROM or "colomajavier@gmail.com"

        await send_email_alert(
            subject=f"🎯 [{campaign_title}] Cita Confirmada: {prospect_name} ({meeting_details})",
            recipient=recipient_email,
            html_content=email_html
        )
    except Exception as email_err:
        logger.error(f"Error dispatching email alert: {email_err}")

async def notify_owner_order_confirmed(
    client_name: str,
    contact_name: Optional[str],
    phone: str,
    city: Optional[str],
    order_draft: Any,
    delivery_notes: Optional[str] = None
) -> None:
    """
    Dispatches instant notification to the business owner/depot about a confirmed customer order.
    """
    alert_phone = settings.WHATSAPP_ALERT_PHONE or "5493434536447"
    contact_str = contact_name or "Comercio"
    city_str = city or "No especificada"

    item_lines = []
    for it in order_draft.items:
        if it.in_stock:
            item_lines.append(f"• {it.quantity}x {it.product.name} ({it.product.presentation}): *{it.formatted_subtotal()}*")

    items_block = "\n".join(item_lines) if item_lines else "Sin items especificados"

    wa_text = (
        f"📦 *¡NUEVO PEDIDO CONFIRMADO!* 📦\n\n"
        f"👤 *Cliente:* {client_name}\n"
        f"📱 *Contacto:* {contact_str} (+{phone})\n"
        f"📍 *Zona/Localidad:* {city_str}\n\n"
        f"📝 *MERCADERÍA SOLICITADA:*\n"
        f"{items_block}\n\n"
        f"💰 *TOTAL ESTIMADO: {order_draft.formatted_total()}*\n"
        f"🚚 *Estado:* Ingresado para armado y reparto.\n\n"
        f"👉 *Contactar cliente:* https://wa.me/{phone}"
    )

    # Slight delay so confirmation reply arrives first in chat
    await asyncio.sleep(1.5)
    await send_whatsapp_message(to_phone=alert_phone, text=wa_text)
    logger.info(f"Order alert dispatched to owner ({alert_phone}) for {client_name}")

    try:
        from app.services.alerts import build_order_html_email
        email_html = build_order_html_email(
            client_name=client_name,
            contact_name=contact_name,
            phone=phone,
            city=city,
            order_items=order_draft.items,
            total_formatted=order_draft.formatted_total(),
            delivery_notes=delivery_notes
        )
        recipient_email = settings.MAIL_USERNAME or settings.MAIL_FROM or "colomajavier@gmail.com"
        await send_email_alert(
            subject=f"📦 [Nuevo Pedido] {client_name} - {order_draft.formatted_total()}",
            recipient=recipient_email,
            html_content=email_html
        )
    except Exception as e:
        logger.error(f"Error dispatching order email alert: {e}")
